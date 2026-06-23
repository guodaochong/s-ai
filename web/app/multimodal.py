from __future__ import annotations

import base64
import re

import structlog

from app.config import MODEL_VISION, logger
from app.llm import call_llm


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
