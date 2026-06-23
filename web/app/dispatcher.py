"""Internal tool dispatcher — routes non-MCP tool calls to in-process handlers.

Each internal tool (flood_sim_3d, building_extract, weather_forecast, etc.)
is registered in a dispatch dict and executed locally rather than delegated
to an MCP microservice.  This keeps latency-sensitive or stateful operations
(e.g. SAM segmentation, 3D reconstruction) within the web process.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Awaitable, Callable

import structlog

from app.config import UPLOAD_IMG_DIR
from app.knowledge import fetch_precipitation_grid, get_weather, kg, search_satellite
from app.services import (
    detect_water_change,
    extract_buildings,
    get_recon_engine,
    monitor_water,
    plan_drone_mission,
    run_multi_agent_debate,
    simulate_flood_3d,
)
from app.tools.generator import generate_tool_with_retry
from app.utils import normalize_auto_tool_result

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

logger = structlog.get_logger(__name__)

_IMG_PATH_PATTERNS = [r"\[上传图片路径:(.+?)\]", r"\[img:(.+?)\]"]


async def _h_weather(args: dict, user_msg: str) -> dict:
    return await get_weather(
        args.get("latitude", 33.19), args.get("longitude", 104.89), args.get("forecast_days", 3),
    )


async def _h_satellite(args: dict, user_msg: str) -> dict:
    return await search_satellite(args.get("bbox"), args.get("date_start", ""), args.get("date_end", ""))


async def _h_kg_query(args: dict, user_msg: str) -> dict:
    q = args.get("query", "")
    entities = kg.query_entities(name=q)
    relations: list[dict] = []
    for e in entities[:3]:
        relations.extend(kg.query_relations(e["name"]))
    return {"entities": entities, "relations": relations}


async def _h_auto_tool(args: dict, user_msg: str) -> dict:
    """Generate + execute a Python tool on the fly via LLM code generation."""
    requirement = args.get("requirement", "")
    if user_msg and len(user_msg) > len(requirement):
        requirement = f"{requirement}。用户原始请求： {user_msg}"

    gen, result, logs = await generate_tool_with_retry(requirement, max_attempts=3)
    for log in logs:
        logger.info("[auto_tool] %s", log)

    if not gen or not result:
        return {"error": "自动工具生成失败，请更具体地描述计算需求"}

    result["_generated_tool"] = gen["tool_name"]
    result["_generated_file"] = gen["file"]
    return normalize_auto_tool_result(result)


async def _h_reconstruct_3d(args: dict, user_msg: str) -> dict:
    """Run TripoSR 3D reconstruction in a background thread."""
    from reconstruct.engine import create_task, get_task_status, _tasks

    image_path = args.get("image_path", "")
    if not image_path:
        return {"error": "缺少 image_path 参数，无法执行3D重建"}

    for pat in _IMG_PATH_PATTERNS:
        m = re.search(pat, image_path)
        if m:
            image_path = m.group(1)
            break

    p = Path(image_path)
    if not p.exists() and not p.is_absolute():
        for candidate in [UPLOAD_IMG_DIR / p.name, UPLOAD_IMG_DIR / image_path]:
            if candidate.exists():
                p = candidate
                break

    if not p.exists():
        return {"error": f"图片文件不存在: {image_path}"}

    eng = get_recon_engine()
    task_id = create_task()
    done_evt = threading.Event()
    run_err: list[str | None] = [None]

    def _run():
        try:
            eng.reconstruct_single(str(p), task_id)
        except Exception as e:
            run_err[0] = str(e)
            if task_id in _tasks:
                _tasks[task_id]["error"] = str(e)
                _tasks[task_id]["stage"] = "error"
        finally:
            done_evt.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    while not done_evt.is_set():
        await asyncio.sleep(1.5)

    status = get_task_status(task_id)
    if run_err[0] or status.get("error"):
        return {"error": run_err[0] or status.get("error", "unknown")}

    meta = status.get("meta", {})
    return {
        "recon_3d": True,
        "glb_url": f"/api/reconstruct/result/{task_id}",
        "task_id": task_id,
        "vertices": meta.get("vertices", 0),
        "faces": meta.get("faces", 0),
        "inference_time": meta.get("inference_time", 0),
        "total_time": meta.get("total_time", 0),
        "vram_peak_gb": meta.get("vram_peak_gb", 0),
        "message": "3D重建任务已创建，请等待处理完成",
    }


async def _h_precipitation(args: dict, user_msg: str) -> dict:
    forecast = args.get("forecast_mode", False) or any(k in user_msg for k in ["预报", "未来"])
    return await fetch_precipitation_grid(
        bbox=args.get("bbox"), grid_size=args.get("grid_size", 8),
        forecast_mode=forecast, location=args.get("location", ""),
    )


async def _h_buildings(args: dict, user_msg: str) -> dict:
    return await extract_buildings(args.get("bbox"), args.get("location"))


async def _h_water_monitor(args: dict, user_msg: str) -> dict:
    return await monitor_water(args.get("bbox"), args.get("location"))


async def _h_water_change(args: dict, user_msg: str) -> dict:
    return await detect_water_change(args.get("bbox"), args.get("location"), args.get("date1", ""), args.get("date2", ""))


async def _h_debate(args: dict, user_msg: str) -> dict:
    return await run_multi_agent_debate(args.get("scenario", ""))


async def _h_flood_sim(args: dict, user_msg: str) -> dict:
    return await simulate_flood_3d(args.get("bbox"), args.get("location"), args.get("rainfall_mm", 100))


async def _h_drone(args: dict, user_msg: str) -> dict:
    return await plan_drone_mission(args.get("bbox"), args.get("location"), args.get("mission_type", "flood_inspect"))


_Handler = Callable[[dict, str], Awaitable[dict]]

_DISPATCH: dict[str, _Handler] = {
    "weather_forecast": _h_weather,
    "satellite_search": _h_satellite,
    "spatial_knowledge_query": _h_kg_query,
    "auto_tool": _h_auto_tool,
    "reconstruct_3d": _h_reconstruct_3d,
    "precipitation_grid": _h_precipitation,
    "building_extract": _h_buildings,
    "water_monitor": _h_water_monitor,
    "water_change": _h_water_change,
    "multi_agent_debate": _h_debate,
    "flood_sim_3d": _h_flood_sim,
    "drone_mission": _h_drone,
}


async def handle_internal_tool(tool_name: str, args: dict, user_msg: str = "") -> dict:
    """Look up *tool_name* in the dispatch table and invoke its handler."""
    handler = _DISPATCH.get(tool_name)
    if handler is None:
        return {"error": f"Unknown internal tool: {tool_name}"}
    result = await handler(args, user_msg)
    return result if isinstance(result, dict) else {"result": str(result)}
