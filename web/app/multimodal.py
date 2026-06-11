from __future__ import annotations

import base64
import re

import structlog

from app.config import MODEL_FLASH, logger
from app.llm import call_llm


async def analyze_image(image_b64: str, prompt: str = "") -> str:
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": prompt or "描述这张图片的内容，特别是与水利/地形/空间分析相关的信息。"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64[:50000]}"}},
        ]},
    ]
    try:
        content, _, _ = await call_llm(messages, model=MODEL_FLASH, use_tools=False, max_tokens_override=2048)
        return content
    except Exception as e:
        logger.error("[Vision] image analysis failed", error=str(e)[:200])
        return f"图片分析失败: {str(e)[:100]}"


async def tree_of_thought(query: str, breadth: int = 3) -> str:
    branches = []
    for i in range(breadth):
        messages = [
            {"role": "system", "content": f"你是水利分析专家。从第{i + 1}个角度分析问题，给出独特见解。简洁回复。"},
            {"role": "user", "content": query},
        ]
        try:
            content, _, _ = await call_llm(messages, model=MODEL_FLASH, use_tools=False, max_tokens_override=1024)
            branches.append(content[:500])
        except Exception:
            pass
    synthesis_msg = [
        {"role": "system", "content": "综合以下多个分析角度，给出最优解答。"},
        {"role": "user", "content": "原始问题: " + query + "\n\n" + "\n---\n".join(branches)},
    ]
    try:
        content, _, _ = await call_llm(synthesis_msg, model=MODEL_FLASH, use_tools=False)
        return content
    except Exception as e:
        return "\n".join(branches) if branches else f"分析失败: {str(e)[:100]}"
