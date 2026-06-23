from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path

import structlog

from app.config import logger

_RUNNER_PATH = str(Path(__file__).parent / "_sandbox_runner.py")

_FORBIDDEN_MODULES = frozenset({
    "os", "subprocess", "shutil", "ctypes", "socket", "pickle",
    "shlex", "multiprocessing", "threading", "signal", "pty",
})

_FORBIDDEN_ATTRS = frozenset({
    "system", "popen", "spawn", "exec", "eval", "run",
    "kill", "terminate", "remove", "unlink", "rmdir",
})

_FORBIDDEN_CALLS = frozenset({
    "exec", "eval", "compile", "__import__", "globals", "locals",
})


def check_code_safety(code: str) -> list[str]:
    """AST-level check for dangerous patterns in LLM-generated code.

    Returns list of issue strings (empty = safe).
    Regex-based check is insufficient; AST catches obfuscated forms.
    """
    issues: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"Syntax error: {e.msg} (line {e.lineno})"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_MODULES:
                    issues.append(f"Forbidden import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in _FORBIDDEN_MODULES:
                    issues.append(f"Forbidden import: {node.module}")
        elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
            issues.append(f"Potentially dangerous attribute: .{node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_CALLS:
                issues.append(f"Forbidden call: {node.func.id}()")
    return issues


class SandboxTimeoutError(Exception):
    pass


def exec_in_sandbox(
    code: str,
    tool_name: str,
    args: dict,
    timeout: float = 30.0,
) -> tuple[dict | None, Exception | None]:
    safety_issues = check_code_safety(code)
    if safety_issues:
        msg = "; ".join(safety_issues[:3])
        logger.warning("[Sandbox] code rejected by safety check", tool=tool_name, issues=safety_issues)
        return {"error": f"Code safety check failed: {msg}"}, None

    args_json = json.dumps(args, ensure_ascii=False, default=str)
    t0 = time.time()

    try:
        result = subprocess.run(
            [sys.executable, _RUNNER_PATH, args_json, tool_name],
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            cwd=str(Path(_RUNNER_PATH).parent),
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.time() - t0) * 1000)
        logger.error("[Sandbox] timeout", tool=tool_name, timeout_s=timeout, elapsed_ms=elapsed)
        return {"error": f"Tool execution exceeded {timeout}s timeout"}, SandboxTimeoutError(f"{timeout}s")
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        logger.error("[Sandbox] subprocess failed", tool=tool_name, elapsed_ms=elapsed, error=str(e)[:200])
        return {"error": f"Sandbox error: {str(e)[:200]}"}, e

    elapsed = int((time.time() - t0) * 1000)

    if result.returncode != 0:
        stderr_tail = result.stderr[-300:] if result.stderr else ""
        logger.error("[Sandbox] non-zero exit", tool=tool_name, code=result.returncode, elapsed_ms=elapsed, stderr=stderr_tail)
        return {"error": f"Sandbox exited {result.returncode}: {stderr_tail}"}, None

    stdout_lines = [ln for ln in result.stdout.strip().split("\n") if ln.strip()]
    if not stdout_lines:
        logger.error("[Sandbox] empty output", tool=tool_name, elapsed_ms=elapsed)
        return {"error": "Sandbox produced no output"}, None

    try:
        data = json.loads(stdout_lines[-1])
    except json.JSONDecodeError as e:
        logger.error("[Sandbox] invalid JSON output", tool=tool_name, elapsed_ms=elapsed, output=stdout_lines[-1][:200])
        return {"error": f"Invalid output format: {str(e)[:100]}"}, e

    if "error" in data:
        logger.warning("[Sandbox] tool returned error", tool=tool_name, elapsed_ms=elapsed, error=data["error"][:100])
    else:
        logger.info("[Sandbox] success", tool=tool_name, elapsed_ms=elapsed)

    return data.get("result") or data, None
