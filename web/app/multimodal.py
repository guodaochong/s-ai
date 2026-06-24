from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

import structlog

from app.config import MODEL_VISION, logger
from app.llm import call_llm

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"


def _resize_image_b64(image_b64: str, max_dim: int = 1024, quality: int = 80) -> str:
    """Downscale an image so its base64 payload stays within GLM-4V limits."""
    try:
        from PIL import Image
        raw = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(raw))
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), Image.LANCZOS)
        if img.mode == "RGBA":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.warning("[Vision] resize failed, using raw", error=str(e)[:100])
        return image_b64


async def analyze_image(image_b64: str, prompt: str = "") -> str:
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": prompt or "分析这张与水利/地理相关的图片，识别关键信息（地形、水域、建筑、植被等），给出结构化描述。"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_resize_image_b64(image_b64)}"}},
        ]},
    ]
    try:
        content, _, _ = await call_llm(messages, model=MODEL_VISION, use_tools=False, max_tokens_override=2048)
        return content
    except Exception as e:
        logger.error("[Vision] image analysis failed", error=str(e)[:200])
        return f"图片分析失败: {str(e)[:100]}"


_DISASTER_PROMPT = """你是水利灾害评估专家。分析这张现场照片，返回JSON格式的灾情评估。

评估内容：水深(参照车辆轮胎0.4m/车身1.5m/门框2m)、灾害类型、严重程度1-5、受淹建筑、安全隐患、建议措施。
非灾害照片返回confidence=0.1。

JSON字段：disaster_type, severity, water_depth_m, depth_basis, affected_buildings(array of type/count/status), affected_roads, hazards(array), estimated_affected_population, recommended_actions(array), confidence, summary。"""


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
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_resize_image_b64(image_b64)}"}},
        ]},
    ]
    try:
        content, _, _ = await call_llm(
            messages, model=MODEL_VISION, use_tools=False, max_tokens_override=1024,
        )
    except Exception as e:
        logger.error("[Vision] disaster assessment failed", error=str(e)[:200])
        return {"error": f"评估失败: {str(e)[:100]}"}

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not match:
        return {"error": "无法解析评估结果", "raw": content[:300]}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {"error": "评估结果格式错误", "raw": content[:300]}
