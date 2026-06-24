from __future__ import annotations

import base64
import json
import re
from typing import Any

import structlog

from app.config import MODEL_VISION, logger
from app.llm import call_llm

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"


async def analyze_image(image_b64: str, prompt: str = "") -> str:
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": prompt or "分析这张与水利/地理相关的图片，识别关键信息（地形、水域、建筑、植被等），给出结构化描述。"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64[:50000]}"}},
        ]},
    ]
    try:
        content, _, _ = await call_llm(messages, model=MODEL_VISION, use_tools=False, max_tokens_override=2048)
        return content
    except Exception as e:
        logger.error("[Vision] image analysis failed", error=str(e)[:200])
        return f"图片分析失败: {str(e)[:100]}"


_DISASTER_PROMPT = """你是水利灾害评估专家。仔细分析这张现场照片，给出结构化灾情评估。

评估要求：
1. 水深估算：寻找画面中的参照物（车辆轮胎约0.4m/轿车车身约1.5m/成年人约1.7m/门框约2m/一层楼约3m），估算水面到地面的深度
2. 建筑受损：识别受淹/损坏/倒塌的建筑，估算数量和类型
3. 道路设施：识别受淹道路/桥梁/电力设施/管线
4. 灾害类型：内涝/洪水/管涌/溃坝/山洪/泥石流/堰塞湖
5. 严重程度：1=轻微(积水<0.3m) 2=较轻(0.3-0.8m) 3=中等(0.8-1.5m) 4=严重(1.5-3m) 5=特大(>3m或建筑倒塌)
6. 安全隐患：急流/暗坑/裸露电线/燃气泄漏/结构不稳/化学品
7. 建议措施：基于严重程度给出3-5条具体行动建议

如果照片明显不是灾害/洪水场景，返回 confidence=0.1, disaster_type="非灾害照片"。

仅返回JSON（不要markdown代码块）：
{"disaster_type":"内涝/洪水/...","severity":1-5,"water_depth_m":0.0,"depth_basis":"参照XX估算","affected_buildings":[{"type":"住宅","count":3,"status":"受淹"}],"affected_roads":"XX路被淹约200m","hazards":["裸露电线","急流"],"estimated_affected_population":50,"recommended_actions":["立即疏散低层居民","封闭XX路段","切断电源"],"confidence":0.8,"summary":"一句话总结灾情"}"""


async def assess_disaster(image_b64: str, user_context: str = "") -> dict[str, Any]:
    """Analyze a disaster/flood photo via GLM-4V and return a structured assessment.

    The model estimates water depth (using reference objects in frame),
    identifies affected buildings/infrastructure, flags safety hazards,
    and recommends emergency actions.

    Returns a dict matching the _DISASTER_PROMPT JSON schema, or
    ``{"error": ...}`` on failure.
    """
    full_prompt = _DISASTER_PROMPT
    if user_context:
        full_prompt += f"\n\n用户补充信息：{user_context[:200]}"

    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": full_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]},
    ]
    try:
        content, _, _ = await call_llm(
            messages, model=MODEL_VISION, use_tools=False, max_tokens_override=1500,
        )
    except Exception as e:
        logger.error("[Vision] disaster assessment failed", error=str(e)[:200])
        return {"error": f"评估失败: {str(e)[:100]}"}

    match = re.search(r'\{.*\}', content, re.DOTALL)
    if not match:
        return {"error": "无法解析评估结果", "raw": content[:300]}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {"error": "评估结果格式错误", "raw": content[:300]}
