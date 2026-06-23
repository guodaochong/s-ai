from __future__ import annotations

import json
import time
from typing import Any

import httpx
import structlog

from app.config import (
    GLM_API_URL, GLM_TOOLS, MODEL_FLASH, ZHIPUAI_API_KEY, logger,
)


async def call_llm(
    messages: list[dict],
    model: str = MODEL_FLASH,
    use_tools: bool = True,
    max_tokens_override: int = 0,
    http_timeout: float = 120.0,
    api_url: str = "",
) -> tuple[str, str, list[dict]]:
    url = api_url or GLM_API_URL
    t0 = time.time()
    msg_count = len(messages)
    logger.info("[LLM] >>> request", model=model, messages=msg_count, use_tools=use_tools, timeout=http_timeout, url=url)
    headers = {"Authorization": f"Bearer {ZHIPUAI_API_KEY}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens_override if max_tokens_override > 0 else 4096,
    }
    if use_tools and GLM_TOOLS:
        payload["tools"] = GLM_TOOLS
        payload["tool_choice"] = "auto"

    try:
        async with httpx.AsyncClient(timeout=http_timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            elapsed = time.time() - t0
            logger.info("[LLM] <<< response", status=resp.status_code, elapsed_ms=int(elapsed * 1000))
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content", "") or ""
            reasoning = msg.get("reasoning_content", "") or ""
            tool_calls = msg.get("tool_calls") or []
            logger.info("[LLM] result", content_len=len(content), reasoning_len=len(reasoning), tool_calls=len(tool_calls), finish_reason=data["choices"][0].get("finish_reason", "?"))
            if tool_calls:
                tc_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                logger.info("[LLM] tool_calls", names=tc_names)
            return content, reasoning, tool_calls
    except httpx.TimeoutException:
        elapsed = time.time() - t0
        logger.error("[LLM] timeout", elapsed_ms=int(elapsed * 1000), model=model)
        return "", "", []
    except httpx.HTTPStatusError as e:
        elapsed = time.time() - t0
        logger.error("[LLM] HTTP error", status=e.response.status_code, elapsed_ms=int(elapsed * 1000))
        return "", "", []
    except Exception as e:
        elapsed = time.time() - t0
        logger.error("[LLM] exception", elapsed_ms=int(elapsed * 1000), error=f"{type(e).__name__}: {str(e)[:200]}")
        return "", "", []
