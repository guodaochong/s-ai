from __future__ import annotations

import json
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

logger = structlog.get_logger(__name__)


async def flood_analyze(
    task_type: str = "assessment",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = parameters or {}
    task_handlers = {
        "assessment": _flood_assessment,
        "inundation": _inundation_sim,
        "drainage_check": _drainage_check,
        "warning": _warning_gen,
    }
    handler = task_handlers.get(task_type)
    if not handler:
        return {"error": f"Unknown task: {task_type}. Available: {list(task_handlers.keys())}"}
    return await handler(params)


async def _flood_assessment(p: dict) -> dict[str, Any]:
    rainfall = p.get("rainfall_mm", 100)
    area = p.get("area_ha", 20)
    imperv = p.get("impervious_pct", 65)
    capacity = p.get("pipe_capacity_cms", 2.0)
    runoff = rainfall * imperv / 100 * 0.85
    overflow = max(0, runoff / 1000 * area * 10000 / 3600 - capacity) * 3600
    depth_cm = overflow / (area * 10000) * 100 if area > 0 else 0
    risk = "low" if depth_cm < 5 else "medium" if depth_cm < 15 else "high" if depth_cm < 30 else "critical"
    return {
        "task": "flood_assessment",
        "rainfall_mm": rainfall,
        "runoff_mm": round(runoff, 2),
        "overflow_volume_m3": round(overflow, 1),
        "avg_flood_depth_cm": round(depth_cm, 1),
        "risk_level": risk,
    }


async def _inundation_sim(p: dict) -> dict[str, Any]:
    import math
    lng = p.get("center_lng", 116.397)
    lat = p.get("center_lat", 39.908)
    radius = p.get("radius_m", 800)
    max_depth = p.get("max_depth_m", 0.5)
    rings = []
    for i in range(5):
        r = radius * (i + 1) / 5
        d = max_depth * (1 - (i / 5) ** 0.5)
        coords = []
        for a in range(0, 360, 30):
            rad = math.radians(a)
            c_lng = lng + r * math.cos(rad) / 111000 / math.cos(math.radians(lat))
            c_lat = lat + r * math.sin(rad) / 111000
            coords.append([round(c_lng, 6), round(c_lat, 6)])
        coords.append(coords[0])
        rings.append({"ring": i + 1, "radius_m": round(r, 1), "depth_m": round(d, 3), "polygon": {"type": "Polygon", "coordinates": [coords]}})
    return {"task": "inundation", "center": [lng, lat], "rings": rings, "total_area_m2": round(math.pi * radius ** 2, 1)}


async def _drainage_check(p: dict) -> dict[str, Any]:
    import math
    d = p.get("diameter_m", 0.8)
    slope = p.get("slope", 0.003)
    n = p.get("manning_n", 0.013)
    q_design = p.get("design_flow_cms", 1.5)
    a = math.pi * (d / 2) ** 2
    rh = d / 4
    v = (1 / n) * rh ** (2 / 3) * slope ** 0.5
    q_cap = v * a
    return {
        "task": "drainage_check",
        "full_flow_capacity_cms": round(q_cap, 3),
        "full_flow_velocity_m_s": round(v, 3),
        "design_flow_cms": q_design,
        "capacity_ratio": round(q_cap / q_design, 3) if q_design > 0 else 0,
        "status": "adequate" if q_cap >= q_design else "undersized",
        "upgrade_diameter_m": round((q_design * n / (0.3125 * slope ** 0.5)) ** (3 / 8) * 2, 3) if q_cap < q_design else None,
    }


async def _warning_gen(p: dict) -> dict[str, Any]:
    rain = p.get("current_rain_mm_hr", 60)
    forecast = p.get("forecast_rain_mm_hr", 80)
    soil = p.get("soil_saturation_pct", 70)
    drain = p.get("drainage_util_pct", 85)
    score = (1 if rain > 50 else 0) * 30 + (1 if forecast > 70 else 0) * 25 + (1 if soil > 60 else 0) * 20 + (1 if drain > 80 else 0) * 25
    level = "blue" if score < 30 else "yellow" if score < 50 else "orange" if score < 70 else "red"
    return {"task": "warning", "risk_score": score, "warning_level": level, "actions": {
        "blue": ["monitor"], "yellow": ["alert_crews", "clear_inlets"],
        "orange": ["deploy_pumps", "close_underpasses", "alert_emergency"],
        "red": ["evacuate", "deploy_all_pumps", "activate_emergency_plan"],
    }[level]}


TOOLS = [
    Tool(name="flood_analyze", description="Perform flood analysis: assessment, inundation, drainage check, warning", inputSchema={
        "type": "object",
        "properties": {
            "task_type": {"type": "string", "enum": ["assessment", "inundation", "drainage_check", "warning"], "default": "assessment"},
            "parameters": {"type": "object"},
        },
        "required": [],
    }),
]

HANDLERS = {"flood_analyze": flood_analyze}

mcp_server = Server("mcp-flood-agent")
sse = SseServerTransport("/messages/")
app = FastAPI(title="Flood Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    handler = HANDLERS.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    try:
        result = await handler(**arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
    except Exception as e:
        logger.exception("tool_error", tool=name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


@app.get("/health")
async def health():
    return {"status": "healthy", "server": "flood-agent", "tools": len(TOOLS)}


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    handler = HANDLERS.get(body.get("name"))
    if not handler:
        return {"error": f"Unknown tool: {body.get('name')}"}
    return await handler(**body.get("arguments", {}))


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=6003)


if __name__ == "__main__":
    main()
