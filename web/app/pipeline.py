"""Pipeline orchestrator — AI-powered multi-tool chaining with visual DAG.

Instead of hardcoded templates, the LLM dynamically generates a tool chain
based on the user's query and a curated catalog of pipeline-capable tools.
The LLM decides: which tools, what order, what label/icon for each step.

Preset templates serve as a fast-path fallback for common patterns.

Multi-scenario mode: the same pipeline runs N times with different rainfall
parameters (e.g. 50 mm / 100 mm / 200 mm).  After all scenarios finish, a
comparison table is emitted so the user can see how flood severity scales
with rainfall at a glance.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, AsyncIterator, Callable

from app.config import TOOL_TO_SERVER
from app.utils import sse

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

ToolExecutor = Callable[[str, dict, str], Any]


_PIPELINE_TOOLS = {
    "dem_analyze":           "DEM地形分析(坡度/坡向/高程统计)",
    "watershed_delineate":   "流域提取(汇水区边界划分)",
    "flow_accumulation":     "河网提取(水流累积/河流网络)",
    "point_query":           "点位高程坡度查询",
    "terrain_profile":       "地形剖面图(纵断面)",
    "design_storm":          "设计暴雨(暴雨强度公式/雨型分配)",
    "runoff_compute":        "径流计算(SCS-CN产汇流)",
    "flood_sim_3d":          "3D洪水淹没模拟(动态水面)",
    "flood_inundation_map":  "洪水淹没范围图(2D)",
    "flood_assessment":      "洪水损失评估(受灾面积/人口/经济)",
    "flood_risk_zones":      "洪水风险分区(风险等级划分)",
    "flood_warning":         "洪水预警(防汛预警等级)",
    "precipitation_grid":    "降雨过程网格分析(面雨量/暴雨中心)",
    "weather_forecast":      "天气预报查询(温度/降水/风速)",
    "building_extract":      "建筑提取(OSM建筑轮廓/分类)",
    "satellite_search":      "卫星影像查询(Sentinel/Landsat)",
    "water_monitor":         "水体监测(水域面积变化)",
    "render_map":            "渲染地图出图(专题图/ choropleth)",
}

_TOOL_ICON = {
    "dem_analyze": "⛰️", "watershed_delineate": "🏞️", "flow_accumulation": "🌊",
    "point_query": "📍", "terrain_profile": "📈", "design_storm": "🌧️",
    "runoff_compute": "💧", "flood_sim_3d": "🌊", "flood_inundation_map": "🗺️",
    "flood_assessment": "🏠", "flood_risk_zones": "🚦", "flood_warning": "⚠️",
    "precipitation_grid": "🌧️", "weather_forecast": "🌤️", "building_extract": "🏢",
    "satellite_search": "🛰️", "water_monitor": "💧", "render_map": "🗺️",
}

_COMPLEXITY_RE = re.compile(
    r"全过程|完整.*分析|综合.*评估|推演|全套|端到端|"
    r"暴雨.*洪水|降雨.*淹没|流域.*分析|建筑.*淹没|"
    r"从.*到.*|先.*再.*|然后"
)

_DEPENDENCIES: dict[str, list[str]] = {
    "runoff_compute":       ["design_storm"],
    "flood_sim_3d":         ["runoff_compute"],
    "flood_inundation_map": ["flood_sim_3d"],
    "flood_assessment":     ["flood_sim_3d"],
    "flood_risk_zones":     ["flood_sim_3d", "flood_inundation_map"],
    "flood_warning":        ["flood_sim_3d"],
}


def _topo_sort(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder steps to satisfy dependency constraints (topological sort)."""
    by_tool = {s["tool"]: s for s in steps}
    ordered: list[dict[str, Any]] = []
    placed: set[str] = set()

    def _place(tool: str, depth: int = 0):
        if tool in placed or tool not in by_tool or depth > 10:
            return
        for dep in _DEPENDENCIES.get(tool, []):
            _place(dep, depth + 1)
        if tool not in placed:
            placed.add(tool)
            ordered.append(by_tool[tool])

    for s in steps:
        _place(s["tool"])

    extras = [s for s in steps if s["tool"] not in placed]
    return ordered + extras


_PIPELINE_PROMPT = """你是水利空间分析专家。用户需要一个复杂分析，请从以下工具中选择3-6个，编排成逻辑合理的执行链。

可用工具：
{tool_list}

用户需求：{query}

编排规则：
- 最多6步，最少3步
- 工具顺序必须逻辑合理：先分析后模拟，先基础后综合
- 如果用户提到降雨/降水/预报，必须包含precipitation_grid，且放在第一步
- 如果用户提到洪水/淹没，必须包含flood_sim_3d
- 渲染地图(render_map)通常是最后一步
- 洪水模拟(flood_sim_3d)前应有设计暴雨(design_storm)和径流计算(runoff_compute)
- 不要重复调用同一工具

仅返回JSON，格式：
{{"name":"中文pipeline名称","icon":"单个emoji","steps":[{{"tool":"工具名","label":"4字中文标签"}}]}}"""


async def _generate_pipeline_with_llm(query: str) -> dict[str, Any] | None:
    from app.llm import call_llm
    from app.config import MODEL_AIR

    tool_list = "\n".join(f"- {k}: {v}" for k, v in _PIPELINE_TOOLS.items())
    prompt = _PIPELINE_PROMPT.format(tool_list=tool_list, query=query[:200])

    try:
        content, _, _ = await call_llm(
            [{"role": "user", "content": prompt}],
            model=MODEL_AIR,
            use_tools=False,
            max_tokens_override=500,
        )
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if not match:
            return None
        plan = json.loads(match.group())
    except Exception:
        return None

    steps_raw = plan.get("steps", [])
    if not (3 <= len(steps_raw) <= 6):
        return None

    steps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in steps_raw:
        tool = s.get("tool", "")
        if tool not in _PIPELINE_TOOLS or tool in seen:
            continue
        seen.add(tool)
        steps.append({
            "tool": tool,
            "label": s.get("label", _PIPELINE_TOOLS[tool][:4])[:6],
            "icon": _TOOL_ICON.get(tool, "⚙️"),
        })

    if len(steps) < 3:
        return None

    steps = _topo_sort(steps)
    _FIRST = {"precipitation_grid", "weather_forecast", "dem_analyze"}
    first = [s for s in steps if s["tool"] in _FIRST]
    first.sort(key=lambda s: list(_FIRST).index(s["tool"]))
    rest = [s for s in steps if s["tool"] not in _FIRST and s["tool"] != "render_map"]
    maps = [s for s in steps if s["tool"] == "render_map"]
    steps = first + rest + maps

    return {
        "name": plan.get("name", "空间分析")[:10],
        "icon": plan.get("icon", "🔬")[:2],
        "steps": steps,
    }


def _is_complex_query(query: str) -> bool:
    return bool(_COMPLEXITY_RE.search(query)) or len(query) > 20 and sum(1 for k in _PIPELINE_TOOLS if any(w in query for w in k.split("_"))) >= 2


async def detect_pipeline(query: str) -> dict[str, Any] | None:
    if not _is_complex_query(query):
        return None
    return await _generate_pipeline_with_llm(query)


def _extract_rainfall(query: str) -> str:
    m = re.search(r"(\d+)\s*mm", query, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(\d+)\s*年一遇", query)
    if m:
        return m.group(1)
    return ""


def _extract_bbox(query: str) -> list[float] | None:
    m = re.search(r'\[(-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\]', query)
    if m:
        vals = [float(m.group(i)) for i in range(1, 5)]
        if vals[2] > vals[0] and vals[3] > vals[1]:
            return vals
    return None


def _build_args(tool: str, location: str, rainfall: str, bbox: list[float] | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if tool == "dem_analyze":
        if location:
            args["location"] = location
    elif tool == "design_storm":
        args["city"] = location or "北京"
        args["return_period"] = int(rainfall) if rainfall and rainfall.isdigit() and int(rainfall) > 10 else 100
    elif tool == "runoff_compute":
        args["rainfall_mm"] = float(rainfall) if rainfall and rainfall.replace(".", "").isdigit() else 150
        args["curve_number"] = 75
    elif tool == "flood_sim_3d":
        if location:
            args["location"] = location
        if bbox:
            args["bbox"] = bbox
        args["duration_h"] = 24
    elif tool == "flood_assessment":
        args["rainfall_mm"] = float(rainfall) if rainfall and rainfall.replace(".", "").isdigit() else 150
        if location:
            args["area_name"] = location
    elif tool == "flood_inundation_map":
        if bbox:
            args["bbox"] = bbox
        elif location:
            args["location"] = location
    elif tool == "building_extract":
        if bbox:
            args["bbox"] = bbox
        elif location:
            args["location"] = location
    elif tool == "precipitation_grid":
        if bbox:
            args["bbox"] = bbox
        elif location:
            args["location"] = location
        args["forecast_mode"] = True
    elif tool == "watershed_delineate" or tool == "flow_accumulation":
        if location:
            args["location"] = location
    elif tool == "weather_forecast":
        _COORDS = {"赤峰": (118.89, 42.26), "天水": (105.72, 34.58), "北京": (116.41, 39.90),
                   "兰州": (103.83, 36.06), "成都": (104.07, 30.57), "西安": (108.94, 34.34)}
        for k, (lon, lat) in _COORDS.items():
            if k in location:
                args["lat"] = lat
                args["lon"] = lon
                break
    elif tool in ("flood_risk_zones", "flood_warning", "satellite_search", "water_monitor", "point_query", "terrain_profile"):
        if location:
            args["location"] = location
    return args


async def execute_pipeline(
    tpl: dict[str, Any],
    query: str,
    location: str,
    trace: Any,
    execute_fn: ToolExecutor,
) -> AsyncIterator[dict]:
    steps: list[dict] = tpl["steps"]
    total = len(steps)

    yield sse({
        "type": "pipeline_start",
        "name": tpl["name"],
        "icon": tpl["icon"],
        "steps": [
            {"id": i + 1, "tool": s["tool"], "label": s["label"], "icon": s["icon"], "status": "pending"}
            for i, s in enumerate(steps)
        ],
    })

    yield sse({"type": "thinking_start", "agent": "pipeline", "label": f"{tpl['icon']} {tpl['name']}"})

    t0 = time.time()
    rainfall = _extract_rainfall(query)
    bbox = _extract_bbox(query)

    for i, step in enumerate(steps):
        tool: str = step["tool"]
        sid = i + 1

        yield sse({"type": "pipeline_step", "step_id": sid, "status": "running"})
        yield sse({"type": "thinking", "agent": "pipeline", "content": f"{step['icon']} 正在执行：{step['label']}（{sid}/{total}）"})

        args = _build_args(tool, location, rainfall, bbox)

        t_step = time.time()
        try:
            result = await execute_fn(tool, args, query)
        except Exception as exc:
            result = {"error": str(exc)[:200]}
        elapsed = int((time.time() - t_step) * 1000)

        server = TOOL_TO_SERVER.get(tool, "")

        if isinstance(result, dict) and "error" not in result:
            yield sse({"type": "tool_start", "server": server, "tool": tool, "step": sid})
            yield sse({"type": "tool_result", "server": server, "tool": tool, "result": result, "elapsed_ms": elapsed})
            yield sse({"type": "pipeline_step", "step_id": sid, "status": "done"})
            yield sse({"type": "thinking", "agent": "pipeline", "content": f"✅ {step['label']}完成 ({elapsed}ms)"})
        else:
            err = result.get("error", "未知错误") if isinstance(result, dict) else str(result)[:200]
            yield sse({"type": "pipeline_step", "step_id": sid, "status": "error", "error": err})
            yield sse({"type": "thinking", "agent": "pipeline", "content": f"⚠️ {step['label']}失败: {err[:60]}"})

    yield sse({"type": "thinking", "agent": "pipeline", "content": f"🎉 {tpl['name']}全部完成，共{total}步"})
    yield sse({"type": "thinking_end", "agent": "pipeline"})
    yield sse({"type": "pipeline_done", "duration_ms": int((time.time() - t0) * 1000), "steps_total": total})


# ══════════════════════════════════════════════════════════════════════
#  Multi-Scenario Comparison Engine
# ══════════════════════════════════════════════════════════════════════

_MULTI_SCENARIO_RE = re.compile(r"对比|比较|多情景|不同.*降雨|分别.*mm|vs|VS")

_METRIC_LABELS: dict[str, str] = {
    "max_depth_m": "最大水深(m)",
    "avg_depth_m": "平均水深(m)",
    "inundated_area_km2": "淹没面积(km²)",
    "affected_population": "受灾人口(人)",
    "economic_loss_wan": "经济损失(万元)",
    "affected_area_km2": "受灾面积(km²)",
    "peak_runoff_m3s": "洪峰流量(m³/s)",
    "total_runoff_m3": "径流总量(万m³)",
    "high_risk_area_km2": "高风险区(km²)",
    "medium_risk_area_km2": "中风险区(km²)",
    "low_risk_area_km2": "低风险区(km²)",
}

_RAINFALL_TO_RETURN_PERIOD: list[tuple[int, int]] = [
    (280, 200), (220, 100), (180, 50), (130, 20), (100, 10), (80, 5),
]


def _return_period_from_rainfall(mm: int) -> int:
    for threshold, period in _RAINFALL_TO_RETURN_PERIOD:
        if mm >= threshold:
            return period
    return 5


def _extract_scenarios(query: str) -> list[dict[str, Any]] | None:
    if not _MULTI_SCENARIO_RE.search(query):
        return None

    rainfalls = [int(x) for x in re.findall(r"(\d+)\s*mm", query, re.IGNORECASE)]
    if len(rainfalls) >= 2:
        return [
            {"id": i, "label": f"{r}mm", "rainfall_mm": r,
             "return_period": _return_period_from_rainfall(r)}
            for i, r in enumerate(rainfalls)
        ]

    periods = [int(x) for x in re.findall(r"(\d+)\s*年一遇", query)]
    if len(periods) >= 2:
        mapping = {5: 80, 10: 100, 20: 130, 50: 180, 100: 220, 200: 280}
        return [
            {"id": i, "label": f"{p}年一遇", "rainfall_mm": mapping.get(p, 150),
             "return_period": p}
            for i, p in enumerate(periods)
        ]

    if re.search(r"对比|比较|多情景", query):
        return [
            {"id": 0, "label": "50mm", "rainfall_mm": 50, "return_period": 5},
            {"id": 1, "label": "100mm", "rainfall_mm": 100, "return_period": 10},
            {"id": 2, "label": "200mm", "rainfall_mm": 200, "return_period": 100},
        ]

    return None


def _extract_metrics(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    m: dict[str, Any] = {}
    if tool == "flood_sim_3d":
        for key_out, keys_in in [
            ("max_depth_m", ["max_depth", "max_depth_m"]),
            ("avg_depth_m", ["avg_depth", "avg_depth_m"]),
            ("inundated_area_km2", ["inundated_area", "inundated_area_km2", "flooded_area"]),
        ]:
            for k in keys_in:
                if k in result and result[k]:
                    m[key_out] = round(float(result[k]), 2)
                    break
    elif tool == "flood_assessment":
        for key_out, keys_in in [
            ("affected_population", ["affected_population", "population"]),
            ("economic_loss_wan", ["economic_loss", "loss", "loss_wan"]),
            ("affected_area_km2", ["affected_area", "area_km2"]),
        ]:
            for k in keys_in:
                if k in result and result[k]:
                    m[key_out] = float(result[k])
                    break
    elif tool == "runoff_compute":
        for key_out, keys_in in [
            ("peak_runoff_m3s", ["peak_runoff", "peak_flow"]),
            ("total_runoff_m3", ["total_volume", "runoff_volume"]),
        ]:
            for k in keys_in:
                if k in result and result[k]:
                    m[key_out] = round(float(result[k]), 1)
                    break
    elif tool == "flood_risk_zones":
        for key_out, keys_in in [
            ("high_risk_area_km2", ["high_risk_area", "high_risk_km2"]),
            ("medium_risk_area_km2", ["medium_risk_area", "medium_risk_km2"]),
            ("low_risk_area_km2", ["low_risk_area", "low_risk_km2"]),
        ]:
            for k in keys_in:
                if k in result and result[k]:
                    m[key_out] = round(float(result[k]), 2)
                    break
    return m


def _build_comparison(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    all_keys: set[str] = set()
    for sc in scenarios:
        all_keys.update(sc.get("metrics", {}).keys())

    table: list[dict[str, Any]] = []
    for key in sorted(all_keys, key=lambda k: list(_METRIC_LABELS.keys()).index(k)
                      if k in _METRIC_LABELS else 999):
        row: dict[str, Any] = {
            "metric": _METRIC_LABELS.get(key, key),
            "key": key,
            "values": [
                {"scenario_id": sc["id"], "label": sc["label"],
                 "value": sc.get("metrics", {}).get(key, 0)}
                for sc in scenarios
            ],
        }
        if len(scenarios) >= 2:
            vals = [v["value"] for v in row["values"]]
            if max(vals) > 0:
                row["delta_pct"] = round((max(vals) - min(vals)) / max(vals) * 100)
        table.append(row)

    labels = " vs ".join(sc["label"] for sc in scenarios)
    return {"summary": f"{labels} 对比完成", "metrics": table}


async def execute_multi_scenario(
    tpl: dict[str, Any],
    scenarios: list[dict[str, Any]],
    query: str,
    location: str,
    trace: Any,
    execute_fn: ToolExecutor,
) -> AsyncIterator[dict]:
    total_steps = len(tpl["steps"])
    bbox = _extract_bbox(query)

    yield sse({
        "type": "multi_scenario_start",
        "name": tpl["name"],
        "icon": tpl["icon"],
        "scenarios": [{"id": s["id"], "label": s["label"]} for s in scenarios],
        "steps_template": [
            {"id": i + 1, "tool": s["tool"], "label": s["label"], "icon": s["icon"]}
            for i, s in enumerate(tpl["steps"])
        ],
    })

    yield sse({
        "type": "thinking_start", "agent": "multi_scenario",
        "label": f"📊 {tpl['name']} · {len(scenarios)}情景对比",
    })

    t0 = time.time()
    all_results: list[dict[str, Any]] = []

    for sc in scenarios:
        sc_id = sc["id"]
        sc_label = sc["label"]
        sc_rainfall = str(sc.get("rainfall_mm", 150))
        sc_period = sc.get("return_period", _return_period_from_rainfall(int(sc_rainfall)))

        yield sse({
            "type": "scenario_start", "scenario_id": sc_id, "label": sc_label,
            "pipeline": {
                "name": tpl["name"], "icon": tpl["icon"],
                "steps": [
                    {"id": i + 1, "tool": s["tool"], "label": s["label"],
                     "icon": s["icon"], "status": "pending"}
                    for i, s in enumerate(tpl["steps"])
                ],
            },
        })

        sc_metrics: dict[str, Any] = {}

        for i, step in enumerate(tpl["steps"]):
            tool = step["tool"]
            sid = i + 1

            yield sse({
                "type": "scenario_step", "scenario_id": sc_id,
                "step_id": sid, "status": "running",
            })
            yield sse({
                "type": "thinking", "agent": "multi_scenario",
                "content": f"📊 [{sc_label}] {step['icon']} {step['label']}（{sid}/{total_steps}）",
            })

            args = _build_args(tool, location, sc_rainfall, bbox)
            if "rainfall_mm" in args:
                args["rainfall_mm"] = float(sc_rainfall)
            if "return_period" in args:
                args["return_period"] = sc_period

            t_step = time.time()
            try:
                result = await execute_fn(tool, args, query)
            except Exception as exc:
                result = {"error": str(exc)[:200]}
            elapsed = int((time.time() - t_step) * 1000)

            server = TOOL_TO_SERVER.get(tool, "")

            if isinstance(result, dict) and "error" not in result:
                yield sse({
                    "type": "tool_start", "server": server, "tool": tool,
                    "step": sid, "scenario_id": sc_id,
                })
                yield sse({
                    "type": "tool_result", "server": server, "tool": tool,
                    "result": result, "elapsed_ms": elapsed, "scenario_id": sc_id,
                })
                yield sse({
                    "type": "scenario_step", "scenario_id": sc_id,
                    "step_id": sid, "status": "done",
                })
                metrics = _extract_metrics(tool, result)
                if metrics:
                    sc_metrics.update(metrics)
            else:
                err = result.get("error", "未知错误") if isinstance(result, dict) else str(result)[:200]
                yield sse({
                    "type": "scenario_step", "scenario_id": sc_id,
                    "step_id": sid, "status": "error", "error": err,
                })

        yield sse({"type": "scenario_done", "scenario_id": sc_id, "metrics": sc_metrics})
        all_results.append({"id": sc_id, "label": sc_label, "metrics": sc_metrics})

    comparison = _build_comparison(all_results)
    yield sse({
        "type": "thinking", "agent": "multi_scenario",
        "content": f"🎉 {comparison['summary']}，共{len(scenarios)}情景 × {total_steps}步",
    })
    yield sse({"type": "thinking_end", "agent": "multi_scenario"})
    yield sse({
        "type": "multi_scenario_done",
        "comparison": comparison,
        "scenarios": all_results,
        "duration_ms": int((time.time() - t0) * 1000),
    })
