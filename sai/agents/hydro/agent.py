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


async def hydro_analyze(
    task_type: str = "runoff",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = parameters or {}
    task_handlers = {
        "runoff": _runoff_analysis,
        "flood_peak": _flood_peak,
        "hydrograph": _hydrograph,
        "water_balance": _water_balance,
    }
    handler = task_handlers.get(task_type)
    if not handler:
        return {"error": f"Unknown task: {task_type}. Available: {list(task_handlers.keys())}"}
    return await handler(params)


async def _runoff_analysis(p: dict) -> dict[str, Any]:
    rainfall = p.get("rainfall_mm", 80)
    cn = p.get("curve_number", 75)
    area = p.get("area_ha", 15)
    s = 25400 / cn - 254
    ia = 0.2 * s
    runoff = max(0, (rainfall - ia) ** 2 / (rainfall + 0.8 * s)) if rainfall > ia else 0
    return {
        "analysis": "scs_cn_runoff",
        "rainfall_mm": rainfall,
        "curve_number": cn,
        "initial_abstraction_mm": round(ia, 2),
        "runoff_mm": round(runoff, 2),
        "runoff_volume_m3": round(runoff / 1000 * area * 10000, 1),
        "runoff_coefficient": round(runoff / rainfall, 4) if rainfall > 0 else 0,
    }


async def _flood_peak(p: dict) -> dict[str, Any]:
    area_km2 = p.get("area_km2", 5.0)
    rainfall_mm = p.get("rainfall_mm", 100)
    tc_min = p.get("time_concentration_min", 30)
    qp = 0.278 * 0.6 * rainfall_mm / (tc_min / 60) * area_km2
    return {
        "analysis": "rational_flood_peak",
        "area_km2": area_km2,
        "rainfall_mm": rainfall_mm,
        "time_of_concentration_min": tc_min,
        "runoff_coefficient": 0.6,
        "peak_flow_cms": round(qp, 3),
    }


async def _hydrograph(p: dict) -> dict[str, Any]:
    import math
    tp = p.get("time_peak_hr", 1.0)
    qp = p.get("peak_flow_cms", 5.0)
    duration = p.get("duration_hr", 6)
    points = []
    for t_idx in range(int(duration * 4) + 1):
        t = t_idx * 0.25
        if t <= tp:
            q = qp * (t / tp) ** 2
        else:
            q = qp * math.exp(-2 * (t - tp) / (duration - tp))
        points.append({"time_hr": t, "flow_cms": round(q, 3)})
    return {"analysis": "synthetic_hydrograph", "time_to_peak_hr": tp, "peak_flow_cms": qp, "duration_hr": duration, "points": points}


async def _water_balance(p: dict) -> dict[str, Any]:
    p_mm = p.get("precipitation_mm", 1200)
    et_mm = p.get("evapotranspiration_mm", 600)
    ro_mm = p.get("runoff_mm", 350)
    ds_mm = p.get("deep_seepage_mm", 50)
    delta_s = p_mm - et_mm - ro_mm - ds_mm
    return {
        "analysis": "water_balance",
        "precipitation_mm": p_mm,
        "evapotranspiration_mm": et_mm,
        "runoff_mm": ro_mm,
        "deep_seepage_mm": ds_mm,
        "storage_change_mm": round(delta_s, 1),
        "closure_error_mm": 0,
        "balance_check": "closed" if abs(delta_s) < 5 else "unclosed",
    }


TOOLS = [
    Tool(name="hydro_analyze", description="Perform hydrological analysis: runoff, flood peak, hydrograph, water balance", inputSchema={
        "type": "object",
        "properties": {
            "task_type": {"type": "string", "enum": ["runoff", "flood_peak", "hydrograph", "water_balance"], "default": "runoff"},
            "parameters": {"type": "object", "description": "Task-specific parameters"},
        },
        "required": [],
    }),
]

HANDLERS = {"hydro_analyze": hydro_analyze}

mcp_server = Server("mcp-hydro-agent")
sse = SseServerTransport("/messages/")
app = FastAPI(title="Hydro Agent")
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
    return {"status": "healthy", "server": "hydro-agent", "tools": len(TOOLS)}


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    handler = HANDLERS.get(body.get("name"))
    if not handler:
        return {"error": f"Unknown tool: {body.get('name')}"}
    return await handler(**body.get("arguments", {}))


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=6002)


if __name__ == "__main__":
    main()
