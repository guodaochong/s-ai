from __future__ import annotations

import hashlib
import re

import structlog

from app.config import (
    ALL_TOOLS, MODEL_AIR, ROUTING_RULES, SIMPLE_KEYWORDS, logger,
)
from app.llm import call_llm

_COMPUTE_FAST = re.compile(
    r'计算|算[出法]|求解|拟合|统计[分分析]|'
    r'生成.*[GeoJSON多边线图]|绘制.*[图线曲线]|画.*[图线]|'
    r'矩阵|表格|曲线图|柱状图|对比曲线|过程图|'
    r'单位线|演进|调洪|水力计算|水头损失|'
    r'标准差|变异系数|偏态|峰态|频率分析|'
    r'渔网|六边形|网格划分|风暴路径|随机游走|'
    r'曼宁公式|海森威廉|试算法|'
    r'流量.*水深|水深.*流量|流速.*流量',
    re.IGNORECASE
)

_COMPUTE_OVERRIDE_EXEMPT = frozenset({
    "point_query", "dem_analyze", "terrain_profile", "flood_inundation_map",
    "design_storm", "explain_concept", "render_map", "search", "rag_search",
    "get_standard",
})

_route_cache: dict[str, str] = {}
_ROUTE_CACHE_MAX = 200

_ROUTE_SYSTEM = """你是路由模块。只回复工具名或SIMPLE。

【最高优先级】以下类型必须路由到 auto_tool：
- 计算/算/公式/求解/拟合/统计/矩阵/表格/曲线/图表/单位线/
- 生成/绘制/画 GeoJSON/多边形/线/图形
- 水力计算/水文计算/暴雨/径流/流量/水深

可用工具：hydrodynamic_2d_sim, get_parameter, explain_concept, search, get_standard, dem_analyze, watershed_delineate, flow_accumulation, terrain_profile, point_query, dem_render, tin_generate, quadtree_subdivide, design_storm, runoff_compute, swmm_simulate, calibrate_suggest, flood_inundation_map, flood_assessment, drainage_assessment, flood_warning, flood_risk_zones, spatial_query, buffer, overlay, coordinate_transform, geometry_properties, validate_data, render_map, weather_forecast, satellite_search, spatial_knowledge_query, scatter_interpolate, rag_search, scenario_compare, storm_flood_pipeline, auto_tool

回复格式：只回复一个工具名，或DIRECT:工具名，或SIMPLE。不要解释。"""


async def route(message: str, history: list[dict]) -> str:
    logger.info("[Route] >>> routing start", message=message[:100])

    if any(kw in message.lower() for kw in SIMPLE_KEYWORDS):
        logger.info("[Route] matched SIMPLE_KEYWORDS", result="SIMPLE")
        return "SIMPLE"

    for pattern, tool in ROUTING_RULES:
        if re.search(pattern, message):
            if _COMPUTE_FAST.search(message) and tool not in _COMPUTE_OVERRIDE_EXEMPT:
                logger.info("[Route] matched ROUTING_RULES but _COMPUTE_FAST overrides", pattern=pattern[:30], tool=tool, result="DIRECT:auto_tool")
                return "DIRECT:auto_tool"
            logger.info("[Route] matched ROUTING_RULES", pattern=pattern[:30], tool=tool, result=f"DIRECT:{tool}")
            return f"DIRECT:{tool}"

    if _COMPUTE_FAST.search(message):
        logger.info("[Route] matched _COMPUTE_FAST regex", result="DIRECT:auto_tool")
        return "DIRECT:auto_tool"

    cache_key = hashlib.md5(message.encode()).hexdigest()
    _route_cache.pop(cache_key, None)

    messages = [{"role": "system", "content": _ROUTE_SYSTEM}, {"role": "user", "content": message}]
    try:
        logger.info("[Route] falling through to LLM routing", model=MODEL_AIR)
        content, _, _ = await __import__("asyncio").wait_for(
            call_llm(messages, model=MODEL_AIR, use_tools=False), timeout=8.0
        )
        content = content.strip()
        if content.startswith("DIRECT:"):
            result = content
        elif content.upper() == "SIMPLE":
            result = "SIMPLE"
        else:
            hit = None
            for t in ALL_TOOLS:
                if t in content:
                    hit = t
                    break
            result = f"DIRECT:{hit}" if hit else "DIRECT:auto_tool"
        logger.info("[Route] LLM routing result", llm_response=content[:80], final_result=result)
    except Exception as e:
        result = "DIRECT:auto_tool"
        logger.warning("[Route] LLM routing failed, fallback to auto_tool", error=f"{type(e).__name__}: {str(e)[:100]}")

    if len(_route_cache) >= _ROUTE_CACHE_MAX:
        _route_cache.pop(next(iter(_route_cache)))
    _route_cache[cache_key] = result
    logger.info("[Route] <<< final decision", result=result)
    return result
