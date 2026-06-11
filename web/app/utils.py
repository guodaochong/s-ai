from __future__ import annotations

import json
import re

import structlog

from app.config import AGENT_LABELS, TOOL_TO_SERVER, logger


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def parse_text_tool_calls(content: str) -> list[dict]:
    if not content or len(content) < 10:
        return []
    results = []

    for m in re.finditer(r'(?:</?tool_calling>|</?tool_call>|</?function_call>)\s*(\{[^}]+\})', content, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            name = obj.get("name", "")
            args = obj.get("arguments", {})
            if name and isinstance(args, dict):
                results.append({"id": f"tc_text_{len(results)}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
        except (json.JSONDecodeError, TypeError):
            pass

    for m in re.finditer(r'\{[^{}]*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{[^{}]*\})\s*\}', content):
        name = m.group(1)
        try:
            args = json.loads(m.group(2))
            results.append({"id": f"tc_text_{len(results)}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
        except (json.JSONDecodeError, TypeError):
            pass

    for m in re.finditer(r'\{"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}', content, re.DOTALL):
        name = m.group(1)
        if any(r["function"]["name"] == name for r in results):
            continue
        try:
            args = json.loads(m.group(2))
            results.append({"id": f"tc_text_{len(results)}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
        except (json.JSONDecodeError, TypeError):
            pass

    _BUILTIN = {"print", "json", "str", "int", "float", "dict", "list", "len", "range", "type", "set", "tuple", "abs", "max", "min", "sum", "round", "sorted", "map", "filter", "open", "True", "False", "None", "def", "class", "return", "if", "for", "while", "with", "import", "from"}
    for m in re.finditer(r'(\w+)\s*\(\s*(\{[^}]*\})\s*\)', content):
        name = m.group(1)
        if name in _BUILTIN or any(r["function"]["name"] == name for r in results):
            continue
        try:
            args = json.loads(m.group(2))
            if isinstance(args, dict):
                results.append({"id": f"tc_text_{len(results)}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
        except (json.JSONDecodeError, TypeError):
            pass

    return results


def detect_ui_action(msg: str) -> str:
    msg_lower = msg.lower().strip()
    if any(k in msg_lower for k in ["3d", "三维", "立体"]):
        return "show_3d"
    if any(k in msg_lower for k in ["卫星", "遥感", "sentinel", "landsat"]):
        return "show_satellite"
    if any(k in msg_lower for k in ["知识图谱", "关系图", "实体关系"]):
        return "show_kg"
    if any(k in msg_lower for k in ["数字孪生", "twin"]):
        return "show_twin"
    return ""


def compress_result(tool: str, result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)[:200]
    if "error" in result:
        return f"ERROR: {result['error'][:150]}"
    if tool == "point_query":
        return f"点位: 高程={result.get('elevation_m','?')}m 坡度={result.get('slope_deg','?')}°"
    if tool == "dem_analyze":
        return f"地形: 坡度{result.get('mean_deg','?')}° 坡向={result.get('aspect',{}).get('dominant','?')}"
    if tool == "terrain_profile":
        return f"剖面: 长{result.get('total_distance_m','?')}m 高差{round(result.get('max_elevation_m',0)-result.get('min_elevation_m',0),1)}m"
    if tool == "hydrodynamic_2d_sim":
        return f"模拟: 峰值水深{result.get('peak_max_depth_m','?')}m 面积{result.get('flooded_area_km2','?')}km2"
    if tool == "flood_inundation_map":
        return f"淹没: 面积{result.get('flooded_area_km2','?')}km2 最大水深{result.get('max_depth_m','?')}m"
    if tool == "flood_assessment":
        return f"评估: 风险等级{result.get('risk_level','?')} 受影响{result.get('affected_area_km2','?')}km2"
    if tool == "flood_warning":
        return f"预警: {result.get('warning_level','?')}级 风险={result.get('risk_score','?')}"
    if tool == "get_parameter":
        entries = result.get("results", [])
        return f"参数({result.get('parameter','?')}): {len(entries)}条 " + "; ".join(json.dumps(e, ensure_ascii=False)[:80] for e in entries[:3])
    if tool == "swmm_simulate":
        return f"SWMM: 峰值{result.get('peak_flow_cms','?')}cms 水深{result.get('max_depth_m','?')}m 溢流{result.get('flooding_pct','?')}%"
    if tool == "calibrate_suggest":
        return f"率定: NSE={result.get('nash_sutcliffe','?')} 误差{result.get('error_pct','?')}%"
    return json.dumps(result, ensure_ascii=False)[:200]


def trim_context(messages: list[dict]) -> list[dict]:
    total = sum(len(m.get("content", "")) for m in messages)
    if total <= 6000:
        return messages
    system = messages[0] if messages and messages[0].get("role") == "system" else None
    rest = messages[1:] if system else messages
    removed = 0
    target = total - 6000
    for i, m in enumerate(rest):
        if removed >= target:
            break
        c = m.get("content", "")
        if len(c) > 800:
            cut = len(c) - 400
            rest[i] = {**m, "content": c[:400] + f"\n...[截断{cut}字符]"}
            removed += cut
        if not removed:
            break
    result = [system, *rest] if system else rest
    cleaned = [result[0]] if result and result[0].get("role") == "system" else []
    source = result[1:] if cleaned else result
    for m in source:
        if m.get("role") == "tool" and (not cleaned or cleaned[-1].get("role") != "assistant" or not cleaned[-1].get("tool_calls")):
            continue
        cleaned.append(m)
    if len(cleaned) < 2 and messages:
        return messages
    return cleaned


async def stream_words(text: str, chunk_size: int = 3):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def format_tool_summary(server: str, tool: str, result: dict | list) -> str:
    if isinstance(result, list):
        return f"[{tool}] 返回{len(result)}条记录"
    if isinstance(result, dict):
        if "error" in result:
            return f"[{tool}] 错误: {result['error'][:80]}"
        if "geojson" in result:
            gj = result["geojson"]
            n = len(gj.get("features", [])) if isinstance(gj, dict) else 0
            return f"[{tool}] GeoJSON: {n}个要素"
        if "data_points" in result:
            return f"[{tool}] 数据点: {len(result['data_points'])}个"
        keys = list(result.keys())[:5]
        return f"[{tool}] 字段: {', '.join(keys)}"
    return f"[{tool}] 完成"


def get_chain_suggestions(tool: str) -> list[dict]:
    chains = {
        "point_query": [{"tool": "dem_analyze", "reason": "扩展地形分析"}],
        "dem_analyze": [{"tool": "render_map", "reason": "渲染地形图"}],
        "flood_inundation_map": [{"tool": "flood_assessment", "reason": "洪水风险评估"}],
        "design_storm": [{"tool": "runoff_compute", "reason": "径流计算"}, {"tool": "flood_inundation_map", "reason": "淹没分析"}],
        "runoff_compute": [{"tool": "flood_assessment", "reason": "洪水评估"}],
        "terrain_profile": [{"tool": "render_map", "reason": "渲染剖面图"}],
    }
    return chains.get(tool, [])
