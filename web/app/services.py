from __future__ import annotations

import json
import re

import structlog

from app.config import logger


WORLD_MODEL_RULES = {
    "flood": {"max_velocity": "5m/s", "max_depth": "10m", "min_slope": "0.0001"},
    "drainage": {"min_pipe_slope": "0.001", "max_velocity": "5m/s", "min_diameter": "0.3m"},
    "hydrology": {"min_cn": "30", "max_cn": "100", "rational_C_range": "0.1-0.95"},
}


def get_world_model_rules(scenario: str) -> list[str]:
    rules = WORLD_MODEL_RULES.get(scenario, {})
    return [f"{k}: {v}" for k, v in rules.items()]


def validate_sim_params(params: dict, sim_type: str) -> dict:
    checks = []
    if sim_type == "hydrodynamic":
        if "duration_hours" in params:
            h = params["duration_hours"]
            checks.append({"param": "duration_hours", "valid": 0 < h <= 72, "warning": "" if 0 < h <= 72 else f"模拟时长{h}h超出合理范围"})
        if "grid_resolution_m" in params:
            r = params["grid_resolution_m"]
            checks.append({"param": "grid_resolution_m", "valid": 0.5 <= r <= 100, "warning": "" if 0.5 <= r <= 100 else f"网格分辨率{r}m不合理"})
    return {"sim_type": sim_type, "checks": checks, "all_valid": all(c["valid"] for c in checks)}


async def run_storm_flood_pipeline(args: dict, user_msg: str) -> dict:
    from app.config import MODEL_FLASH
    from app.llm import call_llm
    import asyncio

    return_period = args.get("return_period", 20)
    duration = args.get("duration_min", 60)
    area_km2 = args.get("area_km2", 10)

    prompt = f"""执行暴雨-洪水全链路分析:
    重现期: {return_period}年
    降雨历时: {duration}分钟
    流域面积: {area_km2}km2
    步骤: 1.设计暴雨 → 2.产流计算(SCS-CN) → 3.汇流计算 → 4.洪峰流量 → 5.风险评估
    返回完整计算结果的JSON。"""

    messages = [
        {"role": "system", "content": "你是水文分析专家。按步骤计算暴雨洪水全链路。返回JSON格式结果。"},
        {"role": "user", "content": prompt},
    ]
    try:
        content, _, _ = await asyncio.wait_for(
            call_llm(messages, model=MODEL_FLASH, use_tools=False, max_tokens_override=4096),
            timeout=30.0
        )
        match = re.search(r'\{[^{].*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"raw_analysis": content[:2000], "return_period": return_period}
    except Exception as e:
        return {"error": f"暴雨洪水链路分析失败: {str(e)[:200]}"}


async def run_scenario_compare(args: dict, user_msg: str) -> dict:
    from app.config import MODEL_FLASH
    from app.llm import call_llm
    import asyncio

    scenarios = args.get("scenarios", [])
    metric = args.get("metric", "洪峰流量")

    prompt = f"""对比以下情景的{metric}:
    情景: {json.dumps(scenarios, ensure_ascii=False) if scenarios else user_msg}
    返回对比结果JSON，包含每个情景的{metric}值和差异分析。"""

    messages = [
        {"role": "system", "content": "你是水文分析专家。对比多个情景的关键指标。返回JSON。"},
        {"role": "user", "content": prompt},
    ]
    try:
        content, _, _ = await asyncio.wait_for(
            call_llm(messages, model=MODEL_FLASH, use_tools=False, max_tokens_override=4096),
            timeout=30.0
        )
        match = re.search(r'\{[^{].*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"raw_comparison": content[:2000]}
    except Exception as e:
        return {"error": f"情景对比失败: {str(e)[:200]}"}


async def handle_internal_tool(tool_name: str, args: dict, user_msg: str = "") -> dict:
    from app.knowledge import get_weather, kg, rag, search_satellite
    from app.validators import physics
    from app.multimodal import analyze_image

    if tool_name == "weather_forecast":
        return await get_weather(args.get("latitude", 33.19), args.get("longitude", 104.89), args.get("forecast_days", 3))

    if tool_name == "satellite_search":
        return await search_satellite(args.get("bbox"), args.get("date_start", ""), args.get("date_end", ""))

    if tool_name == "spatial_knowledge_query":
        entities = kg.query_entities(args.get("query", ""))
        relations = kg.query_relations(args.get("query", ""))
        return {"entities": entities, "relations": relations}

    if tool_name == "auto_tool":
        return await _handle_auto_tool(args, user_msg)

    if tool_name == "scenario_compare":
        return await run_scenario_compare(args, user_msg)

    if tool_name == "storm_flood_pipeline":
        return await run_storm_flood_pipeline(args, user_msg)

    if tool_name == "rag_search":
        return {"results": rag.search(args.get("q", args.get("query", "")), args.get("limit", 5))}

    if tool_name == "validate_manning":
        return physics.validate_manning(args.get("n", 0.025), args.get("R", 1.0), args.get("S", 0.001))

    return {"error": f"Unknown internal tool: {tool_name}"}


async def _handle_auto_tool(args: dict, user_msg: str) -> dict:
    from app.tools import generate_tool_with_retry, exec_generated, delete_generated
    from app.config import GEN_TOOL_DIR

    requirement = args.get("requirement", user_msg)
    gen, result, issues = await generate_tool_with_retry(requirement)
    if not gen or not result:
        return {"error": f"代码生成失败(尝试5次): {'; '.join(issues[-3:])}"}

    tool_name = gen["tool_name"]
    code = gen["code"]
    (GEN_TOOL_DIR / f"{tool_name}.py").write_text(code, encoding="utf-8")

    source = gen.get("_source", "llm")
    return result | {
        "_generated_tool": tool_name,
        "_generated_file": str(GEN_TOOL_DIR / f"{tool_name}.py"),
        "_source": source,
        "geojson_summary": _summarize_geojson(result),
    }


def _summarize_geojson(result: dict) -> str:
    geojson = result.get("geojson")
    if isinstance(geojson, dict):
        n = len(geojson.get("features", []))
        return f"FeatureCollection({n} features)"
    return ""
