from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import structlog
import uvicorn
from scipy.spatial import Voronoi as _ScipyVoronoi
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).parent.parent / ".env")

logger = structlog.get_logger(__name__)


# --- Migrated functions (from app/ modules) ---
from app.tracing import evolution_stats as _evolution_stats
from app.tracing import evolution_suggestions as _evolution_suggestions
from app.validators import inject_commonsense as _inject_commonsense
from app.utils import nativefy as _nativefy
from app.tracing import new_trace as _new_trace
from app.utils import normalize_auto_tool_result as _normalize_auto_tool_result
from app.utils import sanitize_geojson_result as _sanitize_geojson_result
from app.knowledge import search_satellite as _search_satellite
from app.knowledge import fetch_precipitation_grid as _fetch_precipitation_grid
from app.utils import sse as _sse
from app.utils import stream_words as _stream_words
from app.utils import compress_result as _compress_result
from app.validators import debate_validate as _debate_validate
from app.utils import detect_ui_action as _detect_ui_action
from app.utils import format_tool_summary as _format_tool_summary
from app.knowledge import get_weather as _get_weather
from app.utils import trim_context as _trim_context
from app.validators import validate_physics as _validate_physics
from app.validators import validate_result as _validate_result
from app.config import _tool_cache, _circuit_breaker, _last_cache_sweep
from app.mcp_client import call_mcp_tool as _call_mcp_tool, cached_mcp_call as _cached_mcp_call
from app.llm import call_llm as _call_llm
from app.multimodal import analyze_image as _analyze_image
from app.services import extract_buildings as _extract_buildings
from app.services import monitor_water as _monitor_water
from app.services import detect_water_change as _detect_water_change
from app.services import run_multi_agent_debate as _run_multi_agent_debate
from app.services import simulate_flood_3d as _simulate_flood_3d
from app.services import plan_drone_mission as _plan_drone_mission
from app.services import get_recon_engine as _get_recon_engine
from app.router import route as _route
from app.store import MemoryStore
from app.validators import physics as _physics
from app.knowledge import kg as _kg
_memory = MemoryStore()
from app.config import (
    ZHIPUAI_API_KEY, GLM_API_URL, MODEL_FLASH, MODEL_AIR,
    MCP_SERVERS, MAX_REACT_STEPS, AGENT_LABELS, TOOL_TO_SERVER,
    GLM_TOOLS, REACT_SYSTEM_PROMPT, CRITICAL_TOOLS,
    DATA_DIR, GEN_TOOL_DIR, STUDY_BBOX,
)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GEN_TOOL_DIR = DATA_DIR / "generated_tools"
GEN_TOOL_DIR.mkdir(parents=True, exist_ok=True)

for _t in ["weather_forecast", "satellite_search", "spatial_knowledge_query",
            "auto_tool", "reconstruct_3d", "precipitation_grid",
            "building_extract", "water_monitor", "water_change",
            "flood_sim_3d", "drone_mission", "multi_agent_debate"]:
    TOOL_TO_SERVER[_t] = "internal"


_trace_counter = 0



async def _generate_tool(query: str, fix_context: dict | None = None) -> dict | None:
    system_msg = """You are a code generator for a water resources spatial intelligence platform.
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
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg}
    ]
    try:
        code, _, _ = await asyncio.wait_for(_call_llm(messages, model=MODEL_AIR, use_tools=False), timeout=25.0)
        code = re.sub(r'```python\s*', '', code)
        code = re.sub(r'```\s*', '', code)
        code = ''.join(char for char in code if ord(char) < 128 or char in '\n\r\t')
        fn_match = re.search(r'def\s+(\w+)\s*\(', code)
        if not fn_match:
            return None
        fn_name = fn_match.group(1)
        tool_file = GEN_TOOL_DIR / f"{fn_name}.py"
        tool_file.write_text(code, encoding="utf-8")
        TOOL_TO_SERVER[fn_name] = "generated"
        return {"tool_name": fn_name, "code": code[:500], "file": str(tool_file)}
    except Exception:
        return None
        fn_name = fn_match.group(1)
        tool_file = GEN_TOOL_DIR / f"{fn_name}.py"
        tool_file.write_text(code, encoding="utf-8")
        TOOL_TO_SERVER[fn_name] = "generated"
        return {"tool_name": fn_name, "code": code[:500], "file": str(tool_file)}
    except Exception:
        return None






def _check_code_quality(code: str, query: str) -> list[str]:
    issues = []
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


def _check_result_quality(result: dict, query: str) -> list[str]:
    if not result:
        return ["结果为空"]
    if isinstance(result, dict) and "error" in result:
        return [f"工具返回错误: {str(result['error'])[:100]}"]
    issues = []
    wants_polygon = any(kw in query for kw in ["多边形", "polygon", "网格", "grid", "区域", "范围", "蜂巢", "渔网"])
    wants_line = any(kw in query for kw in ["线", "line", "剖面", "profile", "管道", "pipe", "河流"])
    if wants_polygon and "geojson" not in result:
        issues.append("查询需要多边形/网格，但结果缺少geojson字段")
    if wants_line and "geojson" not in result:
        issues.append("查询需要线要素，但结果缺少geojson字段")
    if "geojson" in result:
        gj = result["geojson"]
        if isinstance(gj, dict):
            features = gj.get("features", [])
            if not features:
                issues.append("geojson结果没有features")
    return issues


async def _generate_tool_with_retry(query: str, max_attempts: int = 5) -> tuple[dict | None, dict | None, list[str]]:
    logs = []
    fix_context = None
    for attempt in range(1, max_attempts + 1):
        logs.append(f"[attempt {attempt}/{max_attempts}]")
        gen = await _generate_tool(query, fix_context=fix_context)
        if not gen:
            logs.append("LLM returned no code")
            fix_context = {"error": "LLM did not return valid code", "code": "", "traceback": ""}
            continue

        full_code = ""
        tool_file = GEN_TOOL_DIR / f"{gen['tool_name']}.py"
        if tool_file.exists():
            full_code = tool_file.read_text(encoding="utf-8")

        code_issues = _check_code_quality(full_code, query)
        if code_issues:
            logs.append(f"code quality fail: {'; '.join(code_issues)}")
            fix_context = {"error": "; ".join(code_issues), "code": full_code, "traceback": ""}
            _delete_generated(gen["tool_name"])
            continue

        result = _exec_generated(gen["tool_name"], {})

        if isinstance(result, dict) and "error" in result:
            err_msg = result["error"]
            tb = result.get("traceback", "")
            logs.append(f"exec error: {err_msg[:120]}")
            fix_context = {"error": err_msg, "code": full_code, "traceback": tb}
            _delete_generated(gen["tool_name"])
            continue

        cleaned = _sanitize_geojson_result(result)
        if cleaned is not None:
            result = cleaned

        result_issues = _check_result_quality(result, query)
        if result_issues:
            logs.append(f"result quality fail: {'; '.join(result_issues)}")
            fix_context = {"error": "; ".join(result_issues), "code": full_code, "traceback": ""}
            _delete_generated(gen["tool_name"])
            continue

        logs.append(f"success on attempt {attempt}")
        return gen, result, logs

    logs.append(f"all {max_attempts} attempts failed")
    return None, None, logs


def _delete_generated(tool_name: str):
    f = GEN_TOOL_DIR / f"{tool_name}.py"
    if f.exists():
        f.unlink()
    TOOL_TO_SERVER.pop(tool_name, None)


def _exec_generated(tool_name: str, args: dict) -> dict:
    tool_file = GEN_TOOL_DIR / f"{tool_name}.py"
    if not tool_file.exists():
        return {"error": f"Generated tool {tool_name} not found"}
    code = tool_file.read_text(encoding="utf-8")
    code = re.sub(r'def\s+(\w+)\s*\(\s*kwargs\s*\)', r'def \1(**kwargs)', code)
    code = re.sub(r'def\s+(\w+)\s*\(\s*\)', r'def \1(**kwargs)', code)
    if code != tool_file.read_text(encoding="utf-8"):
        tool_file.write_text(code, encoding="utf-8")
    from app.tools.sandbox import exec_in_sandbox
    result, err = exec_in_sandbox(code, tool_name, args)
    if isinstance(result, dict):
        if "error" in result:
            return result
        return _nativefy(result)
    return {"result": str(result) if result else "No result"}



async def _handle_internal_tool(tool_name: str, args: dict, user_msg: str = "") -> dict:
    if tool_name == "weather_forecast":
        return await _get_weather(args.get("latitude", 33.19), args.get("longitude", 104.89), args.get("forecast_days", 3))
    if tool_name == "satellite_search":
        return await _search_satellite(args.get("bbox"), args.get("date_start", ""), args.get("date_end", ""))
    if tool_name == "spatial_knowledge_query":
        q = args.get("query", "")
        entities = _kg.query_entities(name=q)
        relations = []
        for e in entities[:3]:
            relations.extend(_kg.query_relations(e["name"]))
        return {"entities": entities, "relations": relations}
    if tool_name == "physics_check":
        return _physics.check_range(args.get("value", 0), args.get("param_key", ""))
    if tool_name == "auto_tool":
        requirement = args.get("requirement", "")
        params_json = args.get("params_json", "")
        if user_msg and len(user_msg) > len(requirement):
            requirement = f"{requirement}。用户原始请求： {user_msg}"
        gen, result, logs = await _generate_tool_with_retry(requirement, max_attempts=3)
        for log in logs:
            logger.info(f"[auto_tool] {log}")
        if not gen or not result:
            requirement = f"{requirement}。用户原始请求： {user_msg}"
        result["_generated_tool"] = gen["tool_name"]
        result["_generated_file"] = gen["file"]
        result = _normalize_auto_tool_result(result)
        return result
    if tool_name == "reconstruct_3d":
        import re as _re
        import threading as _threading
        from reconstruct.engine import create_task, get_task_status, _tasks
        image_path = args.get("image_path", "")
        if not image_path:
            return {"error": "缺少 image_path 参数，无法执行3D重建"}
        for pat in [r"\[上传图片路径:(.+?)\]", r"\[img:(.+?)\]"]:
            m = _re.search(pat, image_path)
            if m:
                image_path = m.group(1)
                break
        p = Path(image_path)
        if not p.exists() and not p.is_absolute():
            for candidate in [UPLOAD_IMG_DIR / p.name, UPLOAD_IMG_DIR / image_path, DATA_DIR / "uploads_img" / p.name]:
                if candidate.exists():
                    p = candidate
                    break
        image_path = str(p)
        if not p.exists():
            return {"error": f"图片文件不存在: {image_path}"}
        if not p.is_file():
            return {"error": f"路径不是文件: {image_path}"}
        eng = _get_recon_engine()
        task_id = create_task()
        done_evt = _threading.Event()
        run_err = [None]

        def _run_recon():
            try:
                eng.reconstruct_single(image_path, task_id)
            except Exception as e:
                run_err[0] = str(e)
                if task_id in _tasks:
                    _tasks[task_id]["error"] = str(e)
                    _tasks[task_id]["stage"] = "error"
            finally:
                done_evt.set()

        t = _threading.Thread(target=_run_recon, daemon=True)
        t.start()
        while not done_evt.is_set():
            await asyncio.sleep(1.5)
        status = get_task_status(task_id)
        if run_err[0] or status.get("error"):
            return {"error": run_err[0] or status.get("error", "unknown")}
        meta = status.get("meta", {})
        glb_url = f"/api/reconstruct/result/{task_id}"
        return {
            "recon_3d": True,
            "glb_url": glb_url,
            "task_id": task_id,
            "vertices": meta.get("vertices", 0),
            "faces": meta.get("faces", 0),
            "inference_time": meta.get("inference_time", 0),
            "total_time": meta.get("total_time", 0),
            "vram_peak_gb": meta.get("vram_peak_gb", 0),
            "message": f"3D重建任务已创建，请等待处理完成",
        }
    if tool_name == "precipitation_grid":
        fc = args.get("forecast_mode", False) or any(k in user_msg for k in ["预报", "未来"])
        return await _fetch_precipitation_grid(
            bbox=args.get("bbox"),
            grid_size=args.get("grid_size", 8),
            forecast_mode=fc,
            location=args.get("location", ""),
        )
    if tool_name == "building_extract":
        return await _extract_buildings(args.get("bbox"), args.get("location"))
    if tool_name == "water_monitor":
        return await _monitor_water(args.get("bbox"), args.get("location"))
    if tool_name == "water_change":
        return await _detect_water_change(args.get("bbox"), args.get("location"), args.get("date1", ""), args.get("date2", ""))
    if tool_name == "multi_agent_debate":
        return await _run_multi_agent_debate(args.get("scenario", ""))
    if tool_name == "flood_sim_3d":
        return await _simulate_flood_3d(args.get("bbox"), args.get("location"), args.get("rainfall_mm", 100))
    if tool_name == "drone_mission":
        return await _plan_drone_mission(args.get("bbox"), args.get("location"), args.get("mission_type", "flood_inspect"))
    return {"error": f"Unknown internal tool: {tool_name}"}




app = FastAPI(title="S-AI Web API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
from app.auth import AuthMiddleware
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
async def index():
    from starlette.responses import FileResponse as FR
    resp = FR(Path(__file__).parent / "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "web", "engine": "react-fc-v2", "tools": len(GLM_TOOLS)}


@app.get("/api/servers")
async def list_servers():
    results: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in MCP_SERVERS.items():
            try:
                resp = await client.get(f"{url}/health")
                results[name] = {"url": url, "status": "healthy", "info": resp.json()}
            except Exception:
                results[name] = {"url": url, "status": "offline", "info": None}
    return results


UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/upload")
async def upload_file(file: UploadFile = FastAPIFile(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".geojson", ".json", ".shp", ".zip", ".gpkg", ".kml", ".csv"):
        return {"error": f"Unsupported format: {ext}"}
    dest = UPLOAD_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)
    info: dict[str, Any] = {"filename": file.filename, "size_bytes": len(content), "path": str(dest)}
    if ext in (".geojson", ".json"):
        try:
            data = json.loads(content)
            if data.get("type") == "FeatureCollection":
                info["format"] = "GeoJSON"
                info["features"] = len(data.get("features", []))
            elif data.get("type") in ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"):
                info["format"] = "GeoJSON"
                info["features"] = 1
        except json.JSONDecodeError:
            pass
    return info


@app.get("/api/uploads")
async def list_uploads():
    files = []
    for f in sorted(UPLOAD_DIR.iterdir()):
        if f.is_file():
            stat = f.stat()
            files.append({"filename": f.name, "size_bytes": stat.st_size, "modified": stat.st_mtime})
    return {"files": files, "upload_dir": str(UPLOAD_DIR)}


@app.get("/api/heightmap")
async def heightmap_proxy(size: int = 256):
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"http://127.0.0.1:5007/api/heightmap", params={"size": size})
        return resp.json()


@app.get("/api/chat/stream")
async def chat_stream(q: str, history: str = "", workflows: str = ""):
    async def generate():
        message = q
        t_start = time.time()
        trace = _new_trace(message)
        yield _sse({"type": "start", "message": message})

        if message.startswith("[img:"):
            img_name = message[5:].strip().rstrip("]").strip()
            img_path = UPLOAD_IMG_DIR / img_name
            if img_path.exists():
                img_b64 = base64.b64encode(img_path.read_bytes()).decode()
                yield _sse({"type": "thinking_start", "agent": "vision", "label": "🔍 图片分析"})
                analysis = await _analyze_image(img_b64)
                yield _sse({"type": "thinking", "agent": "vision", "content": analysis[:300]})
                yield _sse({"type": "thinking_end", "agent": "vision"})
                message = f"请分析这张图片({img_name})的视觉内容。以下是AI的图片描述，请结合用户需求给出专业分析：\n{analysis}\n[图片路径:{str(img_path)}]\n\n用户的原始说明：{message.replace(f'[img:{img_name}]', '').strip() or '请分析这张图片的内容'}"

        parsed_history = []
        if history:
            try:
                parsed_history = json.loads(history)
            except (json.JSONDecodeError, TypeError):
                pass

        memory_ctx = ""
        episodes = _memory.recall_episodes(message)
        facts = _memory.recall_facts()
        if facts or episodes:
            fact_str = "; ".join(f"{f['key']}={f['value']}" for f in facts[:5])
            ep_str = "; ".join(e["summary"][:60] for e in episodes[:2])
            memory_ctx = f"\n[历史记忆] 关键事实: {fact_str}\n历史摘要: {ep_str}"
            yield _sse({"type": "memory_recall", "facts": facts[:5], "episodes": [{"summary": e["summary"][:100]} for e in episodes[:2]]})

        commonsense_ctx = _inject_commonsense(message)

        ui_force = _detect_ui_action(message)
        if ui_force:
            yield _sse({"type": "thinking_start", "agent": "react", "label": "🎯 智能操作"})
            yield _sse({"type": "thinking", "agent": "react", "content": f"检测到操作意图：{ui_force}"})
            yield _sse({"type": "thinking_end", "agent": "react"})
            yield _sse({"type": "ui_action", "action": ui_force, "args": {"action": ui_force}})
            labels = {"open_3d": "正在打开3D地形视图...", "open_tin": "正在生成TIN三角网...", "open_quadtree": "正在生成四叉树网格..."}
            async for ch in _stream_words(labels.get(ui_force, f"UI: {ui_force}")):
                yield _sse({"type": "text", "content": ch})
            yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": 0, "trace": trace.to_dict()})
            return

        yield _sse({"type": "thinking_start", "agent": "planner", "label": "🗺️ 意图识别"})
        t_route_start = time.time()
        plan = await _route(message, parsed_history)
        trace.add("route", plan[:80], int((time.time() - t_route_start) * 1000))
        plan_upper = plan.strip().upper()
        is_simple = plan_upper.startswith("SIMPLE")
        is_direct = plan_upper.startswith("DIRECT:")
        direct_tool = plan.split(":", 1)[1].strip() if is_direct else ""
        if is_simple:
            yield _sse({"type": "thinking", "agent": "planner", "content": "简单问候，直接回复。"})
        elif is_direct:
            yield _sse({"type": "thinking", "agent": "planner", "content": f"直接调用工具：{direct_tool}"})
        else:
            yield _sse({"type": "thinking", "agent": "planner", "content": "🤖 分析中，选择合适工具..."})
        yield _sse({"type": "thinking_end", "agent": "planner"})

        react_messages: list[dict] = [
            {"role": "system", "content": REACT_SYSTEM_PROMPT + memory_ctx + "\n" + commonsense_ctx},
            *parsed_history,
            {"role": "user", "content": message},
        ]
        if is_direct:
            react_messages.append({"role": "assistant", "content": f"我将直接调用 {direct_tool} 工具来完成您的需求。"})
        elif not is_simple and plan:
            plan_header = f"""执行计划：
{plan[:800]}

请按计划执行，每步调一个工具。禁止输出代码块。"""
            react_messages.append({"role": "assistant", "content": plan_header})

        react_max = 3 if is_simple else MAX_REACT_STEPS
        executed: set[str] = set()
        total_tools = 0

        yield _sse({"type": "thinking_start", "agent": "react", "label": "🧠 自主推理"})

        for step in range(1, react_max + 1):
            yield _sse({"type": "thinking", "agent": "react", "content": f"━━━ 推理步骤 {step}/{react_max} ━━━"})

            try:
                content, reasoning, tool_calls = await _call_llm(react_messages, model=MODEL_FLASH)
            except Exception as e:
                yield _sse({"type": "thinking", "agent": "react", "content": f"❌ LLM失败: {str(e)[:80]}"})
                break

            if reasoning:
                for line in reasoning.replace(chr(10), '\n').split('\n'):
                    line = line.strip()
                    if line:
                        yield _sse({"type": "thinking", "agent": "react", "content": f"💭 {line[:300]}"})
            else:
                yield _sse({"type": "thinking", "agent": "react", "content": "💭 分析用户请求..."})

            if content and not tool_calls:
                is_multi_step = not is_simple and not is_direct
                if is_multi_step and total_tools < len([l for l in plan.split('\n') if l.strip() and l.strip()[0].isdigit()]):
                    react_messages.append({"role": "user", "content": "计划未完成，请继续调用下一个工具。不要回复文字，只调工具。"})
                    yield _sse({"type": "thinking", "agent": "react", "content": "⏩ 计划未完成，强制继续..."})
                    continue
                yield _sse({"type": "thinking", "agent": "react", "content": f"✅ 推理完成，共{step}步，调用{total_tools}个工具"})
                yield _sse({"type": "thinking_end", "agent": "react"})
                async for ch in _stream_words(content):
                    yield _sse({"type": "text", "content": ch})
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
                return

            if not tool_calls:
                yield _sse({"type": "thinking_end", "agent": "react"})
                async for ch in _stream_words("抱歉，我暂时无法处理您的请求。请描述具体的水利分析需求。"):
                    yield _sse({"type": "text", "content": ch})
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
                return

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
            safe_tool_calls = []
            for tc in tool_calls:
                try:
                    tc_id = tc.get("id", f"tc_{step}_{len(safe_tool_calls)}")
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    arguments = fn.get("arguments", "{}")
                    if not name:
                        continue
                    safe_tool_calls.append({"id": tc_id, "type": "function", "function": {"name": name, "arguments": arguments}})
                except (AttributeError, TypeError):
                    continue
            if not safe_tool_calls:
                yield _sse({"type": "thinking_end", "agent": "react"})
                async for ch in _stream_words("抱歉，工具调用格式异常。请重新描述您的需求。"):
                    yield _sse({"type": "text", "content": ch})
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
                return
            assistant_msg["tool_calls"] = safe_tool_calls
            react_messages.append(assistant_msg)

            deduped_calls = []
            for tc in safe_tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                args_summary = json.dumps(args, ensure_ascii=False)[:100]
                yield _sse({"type": "thinking", "agent": "react", "content": f"🔧 调用 {tool_name}({args_summary})"})
                args_key = hashlib.md5(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                dedup = f"{tool_name}:{args_key}"
                if dedup in executed:
                    yield _sse({"type": "thinking", "agent": "react", "content": f"⏭️ 跳过已执行的工具：{tool_name}"})
                    cache_lookup = hashlib.md5(f"{TOOL_TO_SERVER.get(tool_name, '')}.{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode()).hexdigest()
                    cached_entry = _tool_cache.get(cache_lookup)
                    cached_summary = ""
                    if cached_entry:
                        _, cached_val = cached_entry
                        if isinstance(cached_val, dict):
                            cached_summary = _compress_result(tool_name, cached_val)
                    react_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": cached_summary or "（缓存未命中，重新执行）"})
                    continue
                executed.add(dedup)
                deduped_calls.append((tc["id"], tool_name, args))

            tasks = [(tc_id, tool_name, TOOL_TO_SERVER.get(tool_name, ""), args) for tc_id, tool_name, args in deduped_calls]

            async def _exec_task(tc_id: str, tool_name: str, server: str, args: dict, user_msg: str) -> dict:
                t_tool = time.time()
                logger.debug(f"_exec_task: tool={tool_name}, server={server}, args_keys={list(args.keys())}")
                if server == "generated":
                    r = _exec_generated(tool_name, args)
                    if isinstance(r, dict) and "error" not in r:
                        quality_issues = _check_result_quality(r, user_msg)
                        if quality_issues:
                            logger.info(f"[generated] 质量问题({'; '.join(quality_issues)})，尝试重新生成...")
                            _delete_generated(tool_name)
                            gen, r_new, _ = await _generate_tool_with_retry(f"修复以下工具代码以解决质量问题：{user_msg} -> {tool_name}", max_attempts=2)
                            if gen and r_new:
                                r = r_new
                                r["_generated_tool"] = gen["tool_name"]
                            else:
                                r = {"error": f"工具质量验证失败：{quality_issues[0]}"}
                elif server == "internal":
                    r = await _handle_internal_tool(tool_name, args, user_msg)
                elif not server:
                    gen, r_try, _ = await _generate_tool_with_retry(f"为以下需求自动生成工具：{user_msg} -> {tool_name}", max_attempts=2)
                    if gen and r_try:
                        r = r_try
                        r["_generated_tool"] = gen["tool_name"]
                    else:
                        r = {"error": f"Unknown tool: {tool_name}"}
                else:
                    r = await _cached_mcp_call(server, tool_name, args)
                trace.add(f"tool:{tool_name}", str(server), int((time.time() - t_tool) * 1000))
                return r

            results_raw = await asyncio.gather(*[_exec_task(tc_id, n, s, a, message) for tc_id, n, s, a in tasks], return_exceptions=True)

            for i, ((tc_id, tool_name, server, args), result) in enumerate(zip(tasks, results_raw)):
                if isinstance(result, Exception):
                    result = {"error": str(result)[:200]}

                total_tools += 1
                label = AGENT_LABELS.get(server, server)

                result_keys = list(result.keys()) if isinstance(result, dict) else []
                has_geojson = "geojson" in result_keys
                has_data = "data_points" in result_keys
                has_table = "table" in result_keys
                has_img = "image_base64" in result_keys
                viz_parts = []
                if has_geojson: viz_parts.append("GeoJSON")
                if has_data: viz_parts.append("曲线数据")
                if has_table: viz_parts.append("表格数据")
                if has_img: viz_parts.append("图片数据")
                if viz_parts:
                    yield _sse({"type": "thinking", "agent": "react", "content": f"📊 {tool_name} 返回结果包含可视化数据：{' + '.join(viz_parts)}"})
                elif isinstance(result, dict) and "error" not in result:
                    yield _sse({"type": "thinking", "agent": "react", "content": f"✅ {tool_name} 执行完成，返回字段：{result_keys}"})

                valid, validation_msg = _validate_result(tool_name, args, result if isinstance(result, dict) else {})
                if not valid:
                    yield _sse({"type": "thinking", "agent": "reflect", "content": f"⚠️ 安全检查：{tool_name} 结果异常：{validation_msg}"})
                    yield _sse({"type": "tool_error", "server": server, "tool": tool_name, "error": validation_msg})
                    result = {"error": f"结果验证失败：{validation_msg}", "original_keys": list(result.keys()) if isinstance(result, dict) else []}

                physics_warnings = _validate_physics(tool_name, result if isinstance(result, dict) else {})
                if physics_warnings:
                    yield _sse({"type": "thinking", "agent": "physics", "content": f"⚠️ 物理校验警告：{'; '.join(physics_warnings)}"})

                if tool_name in CRITICAL_TOOLS and isinstance(result, dict) and "error" not in result:
                    debate = await _debate_validate(message, tool_name, result)
                    if not debate["consensus"]:
                        issues = [c.get("issue", "") for c in debate["critics"] if c.get("issue")]
                        yield _sse({"type": "debate", "critics": debate["critics"], "consensus": False})
                        yield _sse({"type": "thinking", "agent": "debate", "content": f"🔍 多智能体辩论发现潜在问题：{'; '.join(issues[:2])}"})
                    else:
                        yield _sse({"type": "debate", "critics": debate["critics"], "consensus": True})

                yield _sse({"type": "divider", "content": f"━━ Step {step}: {label} ▶ {tool_name}"})
                yield _sse({"type": "tool_start", "server": server, "tool": tool_name, "step": total_tools, "react_step": step})
                yield _sse({"type": "tool_result", "server": server, "tool": tool_name, "result": result, "elapsed_ms": 0})

                summary = _format_tool_summary(server, tool_name, result)
                async for ch in _stream_words(summary):
                    yield _sse({"type": "text", "content": ch})

                compressed = _compress_result(tool_name, result) if isinstance(result, dict) else str(result)[:200]
                if not is_simple and not is_direct and plan:
                    compressed += f"\n\n[已完成{total_tools}个工具。请继续执行计划中的下一步工具调用，不要回复文字。]"
                react_messages.append({"role": "tool", "tool_call_id": tc_id, "content": compressed})

            react_messages = _trim_context(react_messages)
            yield _sse({"type": "thinking", "agent": "react", "content": f"📊 已获取{len(deduped_calls)}个工具结果，继续推理..."})

        yield _sse({"type": "thinking", "agent": "react", "content": f"⚠️ 已达最大推理步数({react_max})，总结回复"})
        yield _sse({"type": "thinking_end", "agent": "react"})
        try:
            final_content, _, _ = await _call_llm(react_messages, model=MODEL_AIR, use_tools=False)
            async for ch in _stream_words(final_content):
                yield _sse({"type": "text", "content": ch})
        except Exception:
            async for ch in _stream_words("分析完成。如需更详细结果，请提出更具体的问题。"):
                yield _sse({"type": "text", "content": ch})

        yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": react_max, "tools_called": total_tools, "trace": trace.to_dict()})

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
@app.post("/api/upload_image")
async def upload_image(file: UploadFile = FastAPIFile(...)):
    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"):
        return {"error": f"Unsupported image format: {ext}"}
    ts = int(time.time() * 1000)
    dest = UPLOAD_IMG_DIR / f"{ts}_{file.filename}"
    content = await file.read()
    dest.write_bytes(content)
    return {"filename": dest.name, "size_bytes": len(content), "path": str(dest)}


@app.post("/api/analyze_image")
async def analyze_image_api(image_base64: str = "", file_path: str = ""):
    if file_path:
        import base64
        p = Path(file_path)
        if p.exists():
            image_base64 = base64.b64encode(p.read_bytes()).decode()
        else:
            return {"error": "File not found"}
    if not image_base64:
        return {"error": "Provide image_base64 or file_path"}
    result = await _analyze_image(image_base64)
    return {"analysis": result}


@app.get("/api/memory")
async def get_memory():
    facts = _memory.recall_facts()
    procedures = _memory.recall_procedures("", limit=10)
    return {"facts": facts, "procedures": procedures}


@app.get("/api/weather")
async def get_weather(lat: float = 33.19, lon: float = 104.89, days: int = 3):
    return await _get_weather(lat, lon, days)


@app.get("/api/satellite")
async def get_satellite(date_start: str = "", date_end: str = ""):
    return await _search_satellite(date_start=date_start, date_end=date_end)


@app.get("/api/kg/entities")
async def get_kg_entities(name: str = "", type: str = ""):
    return {"entities": _kg.query_entities(name, type)}


@app.get("/api/kg/relations")
async def get_kg_relations(entity: str = ""):
    return {"relations": _kg.query_relations(entity)}


@app.get("/api/twin/sources")
async def get_twin_sources():
    return {"sources": _twin.list_sources()}


@app.get("/api/twin/status")
async def get_twin_status():
    return {"status": await _twin.health_check()}


@app.get("/api/traces")
async def get_traces():
    return {"traces": [t.to_dict() for t in list(_traces.values())[-20:]]}


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    t = _traces.get(trace_id)
    return t.to_dict() if t else {"error": "not found"}


@app.get("/api/evolution/stats")
async def get_evolution_stats():
    return _evolution_stats()


@app.get("/api/evolution/suggestions")
async def get_evolution_suggestions():
    return {"suggestions": _evolution_suggestions()}


RECON_DIR = Path(__file__).parent / "reconstruct"
RECON_OUTPUTS = RECON_DIR / "outputs"
RECON_OUTPUTS.mkdir(parents=True, exist_ok=True)

@app.post("/api/reconstruct/upload")
async def reconstruct_upload(file: UploadFile = FastAPIFile(...)):
    import uuid as _uuid, threading as _threading
    from reconstruct.engine import create_task, get_task_status, _tasks

    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"):
        return {"error": f"Unsupported format: {ext}"}

    task_id = create_task()
    task_dir = RECON_OUTPUTS / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    img_path = task_dir / f"input{ext}"
    content = await file.read()
    img_path.write_bytes(content)

    def _run():
        try:
            eng = _get_recon_engine()
            eng.reconstruct_single(str(img_path), task_id)
        except Exception as e:
            if task_id in _tasks:
                _tasks[task_id]["error"] = str(e)
                _tasks[task_id]["stage"] = "error"

    t = _threading.Thread(target=_run, daemon=True)
    t.start()

    return {"task_id": task_id}


@app.get("/api/reconstruct/status/{task_id}")
async def reconstruct_status(task_id: str):
    from reconstruct.engine import get_task_status
    status = get_task_status(task_id)
    return status


@app.get("/api/reconstruct/result/{task_id}")
async def reconstruct_result(task_id: str):
    from reconstruct.engine import get_task_status
    status = get_task_status(task_id)
    glb = status.get("output")
    if glb and Path(glb).exists():
        from starlette.responses import FileResponse
        return FileResponse(glb, media_type="model/gltf-binary",
                           filename=f"reconstruction_{task_id}.glb")
    return {"error": "Result not ready"}


@app.get("/api/reconstruct/preview/{task_id}")
async def reconstruct_preview(task_id: str):
    from reconstruct.engine import get_task_status
    status = get_task_status(task_id)
    meta = status.get("meta", {})
    return {
        "task_id": task_id,
        "stage": status.get("stage"),
        "progress": status.get("progress", 0),
        "meta": meta,
        "error": status.get("error"),
    }




if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
