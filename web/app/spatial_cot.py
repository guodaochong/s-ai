"""Spatial Chain-of-Thought engine — AI reasoning visualised on the map.

Instead of a black-box answer, the LLM breaks its spatial reasoning into
discrete steps, each carrying a **map action** (highlight region, draw
arrows, place markers).  Steps are streamed to the frontend where they
are rendered as animated Leaflet layers, letting the user *see* the AI
think spatially.

Trigger phrases: 哪里/为什么/哪个区域/分析.*风险/评估.*安全/
                 最危险/易发/隐患/排查

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

import structlog

from app.config import MODEL_AIR, logger
from app.llm import call_llm
from app.utils import sse

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

logger = structlog.get_logger()


_COT_TRIGGER_RE = re.compile(
    r"哪里.*危险|哪里.*淹|为什么.*洪水|为什么.*淹|哪个区域|"
    r"分析.*风险|评估.*安全|最危险|易发.*灾害|隐患.*排查|"
    r"哪些.*建筑.*风险|哪里.*需要.*疏散|选址|规划.*建议|"
    r"空间推理|空间分析"
)

_COT_PROMPT = """你是水利空间分析专家。用户提出了一个需要空间推理的问题。请将你的推理过程分解为3-5个步骤，每步包含地图可视化操作。

用户问题：{query}
分析区域：{location}

请按以下格式返回每一步：
1. title: 4-8字步骤标题
2. description: 该步骤的推理说明(20-50字)
3. icon: 单个emoji
4. map_action: 地图操作，必须是以下类型之一：
   - highlight_region: 高亮一个矩形区域(需提供bbox[w,s,e,n]、color、label)
   - flow_arrows: 画水流/影响方向箭头(需提供arrows数组，每个{from:[lon,lat],to:[lon,lat]})
   - markers: 标记关键点(需提供points数组，每个{coord:[lon,lat],label,color})
   - circle: 风险圈(需提供center:[lon,lat],radius_km,color,label)
   - polygon: 多边形区域(需提供coords数组[[lon,lat],...],color,label)

坐标范围参考：中国经度73-135，纬度18-53。请基于实际地理位置给出合理坐标。

仅返回JSON：
{{"steps":[{{"title":"","description":"","icon":"","map_action":{{"type":"","params":{{}}}}}}],"conclusion":"最终结论(30-50字)"}}"""


def detect_spatial_cot(query: str) -> bool:
    return bool(_COT_TRIGGER_RE.search(query))


async def generate_spatial_cot(
    query: str,
    location: str = "",
    bbox: list[float] | None = None,
) -> AsyncIterator[dict]:
    t0_total = __import__("time").time()

    yield sse({"type": "thinking_start", "agent": "spatial_cot", "label": "🗺️ 空间思维链"})

    loc_str = location or "未指定区域"
    if bbox:
        loc_str += f" bbox={bbox}"

    prompt = _COT_PROMPT.format(query=query[:200], location=loc_str)

    yield sse({"type": "thinking", "agent": "spatial_cot", "content": "🧠 AI正在分解空间推理步骤..."})

    try:
        content, _, _ = await call_llm(
            [{"role": "user", "content": prompt}],
            model=MODEL_AIR,
            use_tools=False,
            max_tokens_override=2000,
        )
    except Exception as e:
        logger.error("[CoT] LLM failed", error=str(e)[:200])
        yield sse({"type": "thinking", "agent": "spatial_cot", "content": f"❌ 推理失败: {str(e)[:80]}"})
        yield sse({"type": "thinking_end", "agent": "spatial_cot"})
        return

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        yield sse({"type": "thinking", "agent": "spatial_cot", "content": "❌ 无法解析推理结果"})
        yield sse({"type": "thinking_end", "agent": "spatial_cot"})
        return

    try:
        cot_data = json.loads(match.group())
    except json.JSONDecodeError:
        yield sse({"type": "thinking", "agent": "spatial_cot", "content": "❌ 推理结果格式错误"})
        yield sse({"type": "thinking_end", "agent": "spatial_cot"})
        return

    steps = cot_data.get("steps", [])
    conclusion = cot_data.get("conclusion", "")

    if not steps:
        yield sse({"type": "thinking", "agent": "spatial_cot", "content": "❌ 未生成推理步骤"})
        yield sse({"type": "thinking_end", "agent": "spatial_cot"})
        return

    yield sse({
        "type": "spatial_cot_start",
        "total_steps": len(steps),
        "query": query[:100],
    })

    import time
    for i, step in enumerate(steps):
        title = step.get("title", f"步骤{i+1}")
        desc = step.get("description", "")
        icon = step.get("icon", "📍")
        action = step.get("map_action", {})

        yield sse({
            "type": "spatial_cot_step",
            "step_id": i + 1,
            "total": len(steps),
            "title": title,
            "description": desc,
            "icon": icon,
            "map_action": action,
        })

        pause = 0.8
        yield sse({"type": "thinking", "agent": "spatial_cot",
                   "content": f"{icon} Step {i+1}/{len(steps)}: {title} — {desc}"})

        if pause > 0:
            await __import__("asyncio").sleep(pause)

    if conclusion:
        yield sse({"type": "spatial_cot_step", "step_id": len(steps) + 1, "total": len(steps),
                   "title": "结论", "description": conclusion, "icon": "✅", "map_action": {"type": "none", "params": {}}})
        yield sse({"type": "thinking", "agent": "spatial_cot", "content": f"✅ 结论：{conclusion}"})

    elapsed = int((time.time() - t0_total) * 1000)
    yield sse({"type": "spatial_cot_done", "conclusion": conclusion, "steps_total": len(steps), "elapsed_ms": elapsed})
    yield sse({"type": "thinking_end", "agent": "spatial_cot"})
