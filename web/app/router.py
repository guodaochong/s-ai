from __future__ import annotations

import re

from app.config import ROUTING_RULES, SIMPLE_KEYWORDS

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
    "flood_sim_3d", "flood_inundation_map", "flood_assessment",
    "hydrodynamic_2d_sim", "design_storm", "dem_analyze",
    "explain_concept", "search", "rag_search", "get_standard",
    "render_map", "satellite_search", "precipitation_grid",
    "reconstruct_3d", "drone_mission", "water_monitor", "water_change",
    "building_extract", "multi_agent_debate",
})


async def route(message: str, history: list[dict]) -> str:
    if any(kw in message.lower() for kw in SIMPLE_KEYWORDS):
        return "SIMPLE"

    for pattern, tool in ROUTING_RULES:
        if re.search(pattern, message):
            if _COMPUTE_FAST.search(message) and tool not in _COMPUTE_OVERRIDE_EXEMPT:
                return "DIRECT:auto_tool"
            return f"DIRECT:{tool}"

    if _COMPUTE_FAST.search(message):
        return "DIRECT:auto_tool"

    return ""
