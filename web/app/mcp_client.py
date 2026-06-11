from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any

import httpx
import structlog

from app.config import (
    BREAKER_COOLDOWN, BREAKER_THRESHOLD, CACHE_MAX, CACHE_TTL,
    MCP_SERVERS, _circuit_breaker, _last_cache_sweep, _tool_cache, logger,
)


def sweep_cache():
    global _last_cache_sweep
    now = time.time()
    if now - _last_cache_sweep < 60:
        return
    _last_cache_sweep = now
    expired = [k for k, (ts, _) in _tool_cache.items() if now - ts > CACHE_TTL]
    for k in expired:
        del _tool_cache[k]


async def call_mcp_tool(server: str, tool: str, args: dict, retries: int = 2) -> dict:
    url = MCP_SERVERS.get(server, "")
    if not url:
        logger.warning("[MCP] unknown server", server=server, tool=tool)
        return {"error": f"Unknown server: {server}"}
    last_err = ""
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            logger.info("[MCP] >>> call_tool", server=server, tool=tool, url=url, attempt=attempt, args_keys=list(args.keys()))
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{url}/call_tool", json={"name": tool, "arguments": args})
                elapsed = time.time() - t0
                logger.info("[MCP] <<< call_tool response", server=server, tool=tool, status=resp.status_code, elapsed_ms=int(elapsed * 1000))
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "error" in data:
                    logger.warning("[MCP] tool returned error", server=server, tool=tool, error=data["error"][:100])
                return data
        except Exception as e:
            elapsed = time.time() - t0
            last_err = str(e)[:200]
            logger.error("[MCP] call_tool failed", server=server, tool=tool, attempt=attempt, elapsed_ms=int(elapsed * 1000), error=f"{type(e).__name__}: {last_err}")
            if attempt < retries:
                import asyncio
                await asyncio.sleep(0.5 * (attempt + 1))
    return {"error": last_err}


async def cached_mcp_call(server: str, tool: str, args: dict) -> dict:
    breaker_key = f"{server}.{tool}"
    breaker_entry = _circuit_breaker.get(breaker_key)
    if breaker_entry:
        fail_count, last_fail_ts = breaker_entry
        if fail_count >= BREAKER_THRESHOLD and time.time() - last_fail_ts < BREAKER_COOLDOWN:
            remaining = int(BREAKER_COOLDOWN - (time.time() - last_fail_ts))
            logger.warning("[Cache] circuit breaker OPEN", server=server, tool=tool, fail_count=fail_count, remaining_s=remaining)
            return {"error": f"熔断: {tool}连续失败{BREAKER_THRESHOLD}次，{remaining}秒后重试"}
        if fail_count >= BREAKER_THRESHOLD:
            del _circuit_breaker[breaker_key]
            logger.info("[Cache] circuit breaker reset", server=server, tool=tool)

    key = hashlib.md5(f"{server}.{tool}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode()).hexdigest()
    if key in _tool_cache:
        ts, cached = _tool_cache[key]
        if time.time() - ts < CACHE_TTL:
            _tool_cache.move_to_end(key)
            logger.debug("[Cache] HIT", server=server, tool=tool, age_s=int(time.time() - ts))
            return cached
        del _tool_cache[key]

    logger.debug("[Cache] MISS", server=server, tool=tool)
    result = await call_mcp_tool(server, tool, args)

    if isinstance(result, dict) and "error" in result:
        prev = _circuit_breaker.get(breaker_key, (0, 0.0))
        _circuit_breaker[breaker_key] = (prev[0] + 1, time.time())
        logger.warning("[Cache] tool error, breaker count", server=server, tool=tool, count=prev[0] + 1)
    else:
        _circuit_breaker.pop(breaker_key, None)

    _tool_cache[key] = (time.time(), result)
    while len(_tool_cache) > CACHE_MAX:
        _tool_cache.popitem(last=False)
    sweep_cache()
    return result
