"""LLM-powered tool generator — creates, validates, and executes Python code on the fly.

When the ReAct loop encounters a calculation request that no MCP tool covers,
this module asks GLM-4 to write a ``compute_xxx(**kwargs)`` function, saves it
to disk, runs it in a subprocess sandbox, and quality-checks the result.
Failed generations are retried with error context fed back to the LLM.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import asyncio
import re

import structlog

from app.config import GEN_TOOL_DIR, MODEL_AIR, TOOL_TO_SERVER
from app.llm import call_llm
from app.tools.sandbox import exec_in_sandbox
from app.utils import nativefy, sanitize_geojson_result

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

logger = structlog.get_logger(__name__)

_SYSTEM_MSG = """You are a code generator for a water resources spatial intelligence platform.
STRICT RULES:
1. Function signature MUST be: def compute_xxx(**kwargs)
2. Read params via kwargs.get('param_name', default_value), NEVER hardcode
3. Must fully implement the algorithm, NO "simplified"/"TODO"/"approximate"
4. GeoJSON polygons: coordinates must be [[lon,lat],[lon,lat]...], closed ring, NO NaN/Inf
5. For Voronoi: MUST filter out regions containing -1, MUST clip vertices to valid range
6. Output ONLY code, NO imports needed (math,json,np,scipy already available), NO explanation
7. NEVER use emoji or non-ASCII characters
8. CRITICAL: The return dict MUST use EXACTLY these lowercase keys at the TOP level:
   - "geojson": {"type":"FeatureCollection","features":[...]}
   - "points": [{"lat":float, "lng":float, "label":str}]
   - "data_points": [{"x":num, "y":num, "label":str}]
   - "table": [{"col1": val, ...}]
   - "chart_type": "bar" (optional)
   Do NOT nest these under uppercase keys like "GeoJSON" or "Points".
   CORRECT: return {"geojson": geojson_obj, "points": [...], "data_points": [...]}
   WRONG: return {"GeoJSON": {"geojson": geojson_obj}, "Points": {"points": [...]}}

Available: math, json, numpy(as np), scipy.spatial.Voronoi"""


async def generate_tool(query: str, fix_context: dict | None = None) -> dict | None:
    """Call GLM-4 to generate a Python function; save to GEN_TOOL_DIR.

    Args:
        query: Natural-language description of the desired computation.
        fix_context: If set, provides ``{code, error, traceback}`` for bug-fix mode.

    Returns:
        ``{"tool_name": str, "code": str, "file": str}`` on success, ``None`` on failure.
    """
    if fix_context:
        user_msg = (
            f"The following code has a bug, fix it.\n\n"
            f"REQUIREMENT: {query}\n\n"
            f"ORIGINAL CODE:\n```python\n{fix_context.get('code', '')}\n```\n\n"
            f"ERROR:\n{fix_context.get('error', '')}\n\n"
            f"TRACEBACK:\n{fix_context.get('traceback', '')}\n\n"
            f"Output the COMPLETE fixed function. Do NOT simplify or skip any logic."
        )
    else:
        user_msg = f"REQUIREMENT: {query}\n\nGenerate a compute_xxx function with **kwargs signature. Fully implement the algorithm with visualization fields. No simplification!"

    messages = [
        {"role": "system", "content": _SYSTEM_MSG},
        {"role": "user", "content": user_msg},
    ]
    try:
        code, _, _ = await asyncio.wait_for(call_llm(messages, model=MODEL_AIR, use_tools=False), timeout=25.0)
        code = re.sub(r'```python\s*', '', code)
        code = re.sub(r'```\s*', '', code)
        code = ''.join(c for c in code if ord(c) < 128 or c in '\n\r\t')
        fn_match = re.search(r'def\s+(\w+)\s*\(', code)
        if not fn_match:
            return None
        fn_name = fn_match.group(1)
        tool_file = GEN_TOOL_DIR / f"{fn_name}.py"
        tool_file.write_text(code, encoding="utf-8")
        TOOL_TO_SERVER[fn_name] = "generated"
        return {"tool_name": fn_name, "code": code[:500], "file": str(tool_file)}
    except Exception as exc:
        logger.warning("[Generator] tool generation failed", error=str(exc)[:200])
        return None


def check_code_quality(code: str, query: str) -> list[str]:
    """Return a list of quality issues found in *code* (empty list = good)."""
    issues: list[str] = []
    if re.search(r'简化|近似|大概|approximately|simple.*version', code, re.IGNORECASE):
        issues.append("代码包含'简化'或'近似'，可能未完整实现算法")
    if re.search(r'TODO|FIXME', code, re.IGNORECASE):
        issues.append("代码包含TODO/FIXME，存在未完成部分")
    if re.search(r'未实现|待实现', code, re.IGNORECASE):
        issues.append("代码包含'未实现'标记")
    if re.search(r'占位|placeholder', code, re.IGNORECASE):
        issues.append("代码包含占位符")
    if re.search(r'假设|假定', code, re.IGNORECASE):
        issues.append("代码包含假设值，可能未使用真实参数")
    return issues


def check_result_quality(result: dict, query: str) -> list[str]:
    """Return a list of content issues in *result* (empty list = good)."""
    if not result:
        return ["结果为空"]
    if isinstance(result, dict) and "error" in result:
        return [f"工具返回错误: {str(result['error'])[:100]}"]
    issues: list[str] = []
    wants_polygon = any(kw in query for kw in ["多边形", "polygon", "网格", "grid", "区域", "范围", "蜂巢", "渔网"])
    wants_line = any(kw in query for kw in ["线", "line", "剖面", "profile", "管道", "pipe", "河流"])
    if wants_polygon and "geojson" not in result:
        issues.append("查询需要多边形/网格，但结果缺少geojson字段")
    if wants_line and "geojson" not in result:
        issues.append("查询需要线要素，但结果缺少geojson字段")
    if "geojson" in result and isinstance(result["geojson"], dict):
        if not result["geojson"].get("features"):
            issues.append("geojson结果没有features")
    return issues


async def generate_tool_with_retry(query: str, max_attempts: int = 5) -> tuple[dict | None, dict | None, list[str]]:
    """Generate → quality-check → execute → validate, retrying on failure.

    Returns ``(gen_info, result, logs)`` where *logs* captures the attempt trail.
    """
    logs: list[str] = []
    fix_context: dict | None = None

    for attempt in range(1, max_attempts + 1):
        logs.append(f"[attempt {attempt}/{max_attempts}]")
        gen = await generate_tool(query, fix_context=fix_context)
        if not gen:
            logs.append("LLM returned no code")
            fix_context = {"error": "LLM did not return valid code", "code": "", "traceback": ""}
            continue

        tool_file = GEN_TOOL_DIR / f"{gen['tool_name']}.py"
        full_code = tool_file.read_text(encoding="utf-8") if tool_file.exists() else ""

        code_issues = check_code_quality(full_code, query)
        if code_issues:
            logs.append(f"code quality fail: {'; '.join(code_issues)}")
            fix_context = {"error": "; ".join(code_issues), "code": full_code, "traceback": ""}
            delete_generated(gen["tool_name"])
            continue

        result = exec_generated(gen["tool_name"], {})
        if isinstance(result, dict) and "error" in result:
            logs.append(f"exec fail: {result['error']}")
            fix_context = {"error": result["error"], "code": full_code, "traceback": ""}
            delete_generated(gen["tool_name"])
            continue

        cleaned = sanitize_geojson_result(result) if isinstance(result, dict) else None
        if cleaned is not None:
            result = cleaned

        result_issues = check_result_quality(result if isinstance(result, dict) else {}, query)
        if result_issues:
            logs.append(f"result quality fail: {'; '.join(result_issues)}")
            fix_context = {"error": "; ".join(result_issues), "code": full_code, "traceback": ""}
            delete_generated(gen["tool_name"])
            continue

        return gen, result, logs

    return None, None, logs


def delete_generated(tool_name: str) -> None:
    """Remove a generated tool file and deregister it from TOOL_TO_SERVER."""
    f = GEN_TOOL_DIR / f"{tool_name}.py"
    if f.exists():
        f.unlink()
    TOOL_TO_SERVER.pop(tool_name, None)


def exec_generated(tool_name: str, args: dict) -> dict:
    """Execute a previously-generated tool function inside the subprocess sandbox."""
    tool_file = GEN_TOOL_DIR / f"{tool_name}.py"
    if not tool_file.exists():
        return {"error": f"Generated tool {tool_name} not found"}
    original = tool_file.read_text(encoding="utf-8")
    code = re.sub(r'def\s+(\w+)\s*\(\s*kwargs\s*\)', r'def \1(**kwargs)', original)
    code = re.sub(r'def\s+(\w+)\s*\(\s*\)', r'def \1(**kwargs)', code)
    if code != original:
        tool_file.write_text(code, encoding="utf-8")
    result, err = exec_in_sandbox(code, tool_name, args)
    if isinstance(result, dict):
        return result if "error" in result else nativefy(result)
    return {"result": str(result) if result else "No result"}
