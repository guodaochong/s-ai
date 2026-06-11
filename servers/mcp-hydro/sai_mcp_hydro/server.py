from __future__ import annotations

import json
import math
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

logger = structlog.get_logger(__name__)


async def design_storm(
    return_period: int = 50,
    duration_minutes: int = 120,
    time_step_minutes: int = 5,
    city: str = "beijing",
) -> dict[str, Any]:
    params = {
        "beijing": {"A1": 16.861, "C": 0.630, "b": 11.614, "n": 0.726},
        "shanghai": {"A1": 11.648, "C": 0.844, "b": 7.0, "n": 0.650},
        "shenzhen": {"A1": 8.269, "C": 0.698, "b": 4.836, "n": 0.530},
        "guangzhou": {"A1": 13.608, "C": 0.438, "b": 1.462, "n": 0.560},
        "chengdu": {"A1": 10.436, "C": 0.650, "b": 8.0, "n": 0.700},
    }
    p = params.get(city, params["beijing"])
    q_peak = 167 * p["A1"] * (1 + p["C"] * math.log10(return_period)) / ((duration_minutes + p["b"]) ** p["n"])

    total_depth_mm = q_peak * duration_minutes / 10000.0

    n_steps = duration_minutes // time_step_minutes
    peak_step = n_steps // 2
    rainfall = []
    for i in range(n_steps):
        t = (i + 1) * time_step_minutes
        ratio = math.exp(-((i - peak_step) ** 2) / (2 * (n_steps / 6) ** 2))
        intensity = q_peak * ratio / sum(math.exp(-((j - peak_step) ** 2) / (2 * (n_steps / 6) ** 2)) for j in range(n_steps))
        rainfall.append({
            "time_minutes": t,
            "intensity_mm_per_hr": round(intensity, 3),
            "cumulative_mm": round(intensity * time_step_minutes / 60, 3),
        })

    return {
        "city": city,
        "return_period_years": return_period,
        "duration_minutes": duration_minutes,
        "peak_intensity_mm_per_hr": round(q_peak, 3),
        "total_depth_mm": round(total_depth_mm, 2),
        "time_step_minutes": time_step_minutes,
        "rainfall_series": rainfall,
        "formula": f"q = 167 x {p['A1']} x (1+{p['C']}xlg{return_period}) / ({duration_minutes}+{p['b']})^{p['n']}",
    }


async def runoff_compute(
    rainfall_mm: float = 50.0,
    curve_number: int = 75,
    drainage_area_ha: float = 10.0,
    method: str = "scs_cn",
) -> dict[str, Any]:
    s = 25400 / curve_number - 254
    ia = 0.2 * s
    if rainfall_mm <= ia:
        runoff_mm = 0
    else:
        runoff_mm = (rainfall_mm - ia) ** 2 / (rainfall_mm + 0.8 * s)
    runoff_volume_m3 = runoff_mm / 1000 * drainage_area_ha * 10000
    runoff_coeff = runoff_mm / rainfall_mm if rainfall_mm > 0 else 0
    return {
        "method": method,
        "rainfall_mm": rainfall_mm,
        "curve_number": curve_number,
        "drainage_area_ha": drainage_area_ha,
        "initial_abstraction_mm": round(ia, 2),
        "max_retention_mm": round(s, 2),
        "runoff_depth_mm": round(runoff_mm, 3),
        "runoff_volume_m3": round(runoff_volume_m3, 1),
        "runoff_coefficient": round(runoff_coeff, 4),
    }


def _build_inp(
    project_name: str, area_ha: float, slope_pct: float, imperv_pct: float,
    pipe_diam_m: float, pipe_len_m: float, n_sub: int, rainfall_mm_hr: float, duration_min: int,
) -> str:
    sub_area_acre = area_ha / n_sub * 2.47105
    diam_ft = pipe_diam_m * 3.28084
    rain_in_hr = rainfall_mm_hr * 0.0393701
    seg_len_ft = pipe_len_m * 3.28084 / max(n_sub - 1, 1)
    hours = duration_min // 60
    mins = duration_min % 60
    end_time = f"{hours:02d}:{mins:02d}:00"

    lines = [
        "[TITLE]", f";;{project_name}", "",
        "[OPTIONS]",
        "FLOW_UNITS           CFS",
        "INFILTRATION         HORTON",
        "FLOW_ROUTING         DYNWAVE",
        "START_DATE           01/01/2000", "START_TIME           00:00:00",
        "REPORT_START_DATE    01/01/2000", "REPORT_START_TIME    00:00:00",
        f"END_DATE             01/01/2000", f"END_TIME             {end_time}",
        "SWEEP_START          01/01", "SWEEP_END            12/31",
        "DRY_DAYS             5", "WET_STEP             00:01:00",
        "DRY_STEP             01:00:00", "ROUTING_STEP         0:00:30",
        "NORMAL_FLOW_LIMITED  BOTH", "LINK_OFFSETS         DEPTH",
        "MIN_SLOPE            0", "ALLOW_PONDING        NO",
        "SKIP_STEADY_STATE    NO", "",
        "[EVAPORATION]", "CONSTANT         0.0", "DRY_ONLY         NO", "",
        "[RAINGAGES]",
        ";;Name           Format    Interval SCF      Source",
        "RG1              INTENSITY 0:05     1.0      TIMESERIES TS_Rain", "",
        "[SUBCATCHMENTS]",
        ";;Name           Rain Gage        Outlet           Area     %Imperv  Width    %Slope   CurbLen  SnowPack",
    ]
    for i in range(n_sub):
        width_ft = math.sqrt(sub_area_acre * 43560) * (1 if i % 2 == 0 else 0.8)
        lines.append(f"S{i+1}              RG1              J{i+1}              {sub_area_acre:.2f}     {imperv_pct:.0f}       {width_ft:.0f}      {slope_pct:.1f}      0")
    lines += ["", "[SUBAREAS]",
              ";;Subcatchment   N-Imperv   N-Perv     S-Imperv   S-Perv     PctZero    RouteTo    PctRouted"]
    for i in range(n_sub):
        lines.append(f"S{i+1}               0.013      0.15       0.08       0.20       25         OUTLET")
    lines += ["", "[INFILTRATION]",
              ";;Subcatchment   MaxRate    MinRate    Decay      DryTime    MaxInfil"]
    for i in range(n_sub):
        lines.append(f"S{i+1}               3.0        0.5        4          7          0")
    lines += ["", "[JUNCTIONS]",
              ";;Name           Elevation  MaxDepth   InitDepth  SurDepth   Aponded"]
    for i in range(n_sub):
        elev = 150.0 - i * 1.0
        lines.append(f"J{i+1}               {elev:.1f}      10         0          0          0")
    outfall_elev = 150.0 - n_sub * 1.0 - 5.0
    lines += ["", "[OUTFALLS]",
              ";;Name           Elevation  Type       Stage Data       Gated    Route To",
              f"OUT1             {outfall_elev:.1f}      FREE                        NO", ""]
    lines += ["[CONDUITS]",
              ";;Name           From Node        To Node          Length     Roughness  InOffset   OutOffset  InitFlow   MaxFlow"]
    for i in range(n_sub):
        to = f"J{i+2}" if i < n_sub - 1 else "OUT1"
        lines.append(f"C{i+1}               J{i+1}               {to}              {seg_len_ft:.0f}        0.013      0          0          0          0")
    lines += ["", "[XSECTIONS]",
              ";;Link           Shape        Geom1            Geom2      Geom3      Geom4      Barrels    Culvert"]
    for i in range(n_sub):
        lines.append(f"C{i+1}               CIRCULAR     {diam_ft:.2f}              0          0          0          1")
    lines += ["", "[TIMESERIES]",
              ";;Name           Date       Time       Value",
              f"TS_Rain                     0:00       {rain_in_hr:.4f}",
              f"TS_Rain                     {end_time}       {rain_in_hr:.4f}", ""]
    lines += ["[REPORT]", "SUBCATCHMENTS ALL", "NODES ALL", "LINKS ALL", "",
              "[MAP]", "DIMENSIONS       0.000     0.000     10000.000 10000.000",
              "Units            None"]
    return "\n".join(lines)


async def swmm_create_model(
    project_name: str = "sai_demo",
    area_hectares: float = 10.0,
    slope_percent: float = 0.5,
    impervious_percent: float = 60.0,
    pipe_diameter_m: float = 0.8,
    pipe_length_m: float = 500.0,
    n_subcatchments: int = 4,
) -> dict[str, Any]:
    from pathlib import Path
    model_dir = Path(__file__).parent.parent.parent.parent / "data" / "swmm_models"
    model_dir.mkdir(parents=True, exist_ok=True)
    inp_path = model_dir / f"{project_name}.inp"
    inp_text = _build_inp(
        project_name, area_hectares, slope_percent, impervious_percent,
        pipe_diameter_m, pipe_length_m, n_subcatchments, 80.0, 120,
    )
    inp_path.write_text(inp_text, encoding="utf-8")

    subcatchments = []
    sub_area = area_hectares / n_subcatchments
    for i in range(n_subcatchments):
        subcatchments.append({
            "name": f"S{i+1}", "area_ha": round(sub_area, 2),
            "impervious_pct": impervious_percent, "slope_pct": slope_percent,
            "outlet": f"J{i+1}",
        })
    conduits = []
    for i in range(n_subcatchments):
        to = f"J{i+2}" if i < n_subcatchments - 1 else "OUT1"
        conduits.append({
            "name": f"C{i+1}", "from_node": f"J{i+1}", "to_node": to,
            "length_m": round(pipe_length_m / max(n_subcatchments - 1, 1), 1),
            "diameter_m": pipe_diameter_m, "manning_n": 0.013,
        })
    return {
        "project_name": project_name, "inp_file": str(inp_path),
        "n_subcatchments": n_subcatchments, "n_conduits": len(conduits),
        "subcatchments": subcatchments, "conduits": conduits,
        "outfall": {"name": "OUT1", "type": "FREE"},
        "status": "model_created",
    }


async def swmm_simulate(
    project_name: str = "sai_demo",
    rainfall_mm_hr: float = 80.0,
    duration_min: int = 120,
) -> dict[str, Any]:
    from pathlib import Path
    from pyswmm import Simulation, Nodes, Links

    model_dir = Path(__file__).parent.parent.parent.parent / "data" / "swmm_models"
    inp_path = model_dir / f"{project_name}.inp"

    if not inp_path.exists():
        await swmm_create_model(project_name=project_name)
    inp_path = model_dir / f"{project_name}.inp"

    try:
        node_results = {}
        link_results = {}
        time_series = []
        peak_flow_cms = 0.0
        max_depth_m = 0.0
        total_flooding_ft3 = 0.0

        with Simulation(str(inp_path)) as sim:
            sim.step_advance(300)
            nodes = Nodes(sim)
            links = Links(sim)
            for step in sim:
                t_min = (sim.current_time.hour * 60 + sim.current_time.minute
                         + sim.current_time.second / 60)
                sys_flow = 0.0
                for node in nodes:
                    nid = node.nodeid
                    d = node.depth
                    f = node.flooding
                    if nid not in node_results:
                        node_results[nid] = {"max_depth_ft": 0, "flooding_ft3": 0, "peak_inflow": 0}
                    node_results[nid]["max_depth_ft"] = max(node_results[nid]["max_depth_ft"], d)
                    node_results[nid]["flooding_ft3"] += f * 300
                    node_results[nid]["peak_inflow"] = max(node_results[nid]["peak_inflow"], node.total_inflow)
                    sys_flow += node.total_inflow
                for link in links:
                    lid = link.linkid
                    if lid not in link_results:
                        link_results[lid] = {"peak_flow_cfs": 0, "max_depth_ft": 0}
                    link_results[lid]["peak_flow_cfs"] = max(link_results[lid]["peak_flow_cfs"], link.flow)
                    link_results[lid]["max_depth_ft"] = max(link_results[lid]["max_depth_ft"], link.depth)

                flow_cms = sys_flow * 0.0283168
                peak_flow_cms = max(peak_flow_cms, flow_cms)
                time_series.append({
                    "time_min": round(t_min, 1),
                    "flow_cms": round(flow_cms, 3),
                    "depth_m": round(max(
                        (node_results[n]["max_depth_ft"] * 0.3048) for n in node_results
                    ) if node_results else 0, 3),
                })

            for n in node_results:
                node_results[n]["max_depth_m"] = round(node_results[n]["max_depth_ft"] * 0.3048, 3)
                node_results[n]["flooding_m3"] = round(node_results[n]["flooding_ft3"] * 0.0283168, 3)
                node_results[n]["peak_inflow_cms"] = round(node_results[n]["peak_inflow"] * 0.0283168, 3)
                max_depth_m = max(max_depth_m, node_results[n]["max_depth_m"])
                total_flooding_ft3 += node_results[n]["flooding_ft3"]

            for lk in link_results:
                link_results[lk]["peak_flow_cms"] = round(link_results[lk]["peak_flow_cfs"] * 0.0283168, 3)
                link_results[lk]["max_depth_m"] = round(link_results[lk]["max_depth_ft"] * 0.3048, 3)

        total_flooding_m3 = total_flooding_ft3 * 0.0283168
        rain_vol_m3 = rainfall_mm_hr / 1000 / 60 * duration_min * 10 * 10000
        flooding_pct = round(total_flooding_m3 / rain_vol_m3 * 100, 1) if rain_vol_m3 > 0 else 0
        overflow = [n for n, r in node_results.items() if r["flooding_m3"] > 0.01]

        # Downsample time series
        step = max(1, len(time_series) // 16)
        time_series = time_series[::step]

        return {
            "project": project_name, "engine": "PySWMM",
            "rainfall_mm_hr": rainfall_mm_hr, "duration_min": duration_min,
            "peak_flow_cms": round(peak_flow_cms, 3),
            "max_depth_m": round(max_depth_m, 3),
            "flooding_pct": flooding_pct,
            "total_runoff_m3": round(peak_flow_cms * duration_min * 60 * 0.5, 1),
            "total_flooding_m3": round(total_flooding_m3, 1),
            "time_series": time_series,
            "overflow_nodes": overflow,
            "node_stats": {k: {"max_depth_m": v["max_depth_m"], "flooding_m3": v["flooding_m3"],
                                "peak_inflow_cms": v["peak_inflow_cms"]} for k, v in node_results.items()},
            "link_stats": {k: {"peak_flow_cms": v["peak_flow_cms"], "max_depth_m": v["max_depth_m"]}
                           for k, v in link_results.items()},
            "routing_error_pct": round(sim.flow_routing_error, 2),
        }
    except Exception as e:
        logger.exception("pyswmm_error", project=project_name)
        peak_flow = rainfall_mm_hr / 3600 * 10 * 0.6
        max_depth = min(0.8, peak_flow / (0.3 * 0.8))
        flooding_pct = max(0, (rainfall_mm_hr - 60) / rainfall_mm_hr * 100)
        ts = []
        for t in range(0, duration_min + 1, 15):
            r = min(1.0, t / (duration_min * 0.4)) if t < duration_min * 0.5 else max(0, 1 - (t - duration_min * 0.5) / (duration_min * 0.5))
            ts.append({"time_min": t, "flow_cms": round(peak_flow * r, 3), "depth_m": round(max_depth * r, 3)})
        return {
            "project": project_name, "engine": "fallback",
            "error": str(e),
            "rainfall_mm_hr": rainfall_mm_hr, "duration_min": duration_min,
            "peak_flow_cms": round(peak_flow, 3), "max_depth_m": round(max_depth, 3),
            "flooding_pct": round(flooding_pct, 1),
            "total_runoff_m3": round(peak_flow * duration_min * 60 * 0.5, 1),
            "time_series": ts,
            "overflow_nodes": ["J2", "J3"] if flooding_pct > 10 else [],
        }


async def calibrate_suggest(
    observed_peak_flow: float = 1.5,
    simulated_peak_flow: float = 2.0,
    nash_sutcliffe: float = 0.65,
) -> dict[str, Any]:
    error_pct = (simulated_peak_flow - observed_peak_flow) / observed_peak_flow * 100
    suggestions = []
    if error_pct > 20:
        suggestions.append({"parameter": "manning_n_conduit", "direction": "increase", "reason": "simulated peak too high, increase roughness"})
    if error_pct < -20:
        suggestions.append({"parameter": "manning_n_conduit", "direction": "decrease", "reason": "simulated peak too low, decrease roughness"})
    if nash_sutcliffe < 0.5:
        suggestions.append({"parameter": "subcatchment_width", "direction": "adjust", "reason": "N-S < 0.5, subcatchment width affects timing"})
    if nash_sutcliffe < 0.7:
        suggestions.append({"parameter": "impervious_pct", "direction": "adjust", "reason": "N-S < 0.7, check impervious percentage"})
    return {
        "observed_peak_cms": observed_peak_flow,
        "simulated_peak_cms": simulated_peak_flow,
        "error_pct": round(error_pct, 1),
        "nash_sutcliffe": nash_sutcliffe,
        "nse_rating": "excellent" if nash_sutcliffe > 0.9 else "good" if nash_sutcliffe > 0.7 else "acceptable" if nash_sutcliffe > 0.5 else "unsatisfactory",
        "suggestions": suggestions,
    }


TOOLS = [
    Tool(name="design_storm", description="Generate design storm hyetograph using city-specific intensity-duration-frequency formula", inputSchema={"type": "object", "properties": {"return_period": {"type": "integer", "default": 50, "description": "Return period in years (P)"},"duration_minutes": {"type": "integer", "default": 120}, "time_step_minutes": {"type": "integer", "default": 5}, "city": {"type": "string", "default": "beijing", "enum": ["beijing","shanghai","shenzhen","guangzhou","chengdu"]}}, "required": []}),
    Tool(name="runoff_compute", description="Compute runoff using SCS-CN method", inputSchema={"type": "object", "properties": {"rainfall_mm": {"type": "number", "default": 50}, "curve_number": {"type": "integer", "default": 75}, "drainage_area_ha": {"type": "number", "default": 10}, "method": {"type": "string", "default": "scs_cn"}}, "required": []}),
    Tool(name="swmm_create_model", description="Create a simplified SWMM drainage model", inputSchema={"type": "object", "properties": {"project_name": {"type": "string", "default": "sai_demo"}, "area_hectares": {"type": "number", "default": 10}, "impervious_percent": {"type": "number", "default": 60}, "pipe_diameter_m": {"type": "number", "default": 0.8}, "n_subcatchments": {"type": "integer", "default": 4}}, "required": []}),
    Tool(name="swmm_simulate", description="Run SWMM simulation with rainfall input", inputSchema={"type": "object", "properties": {"project_name": {"type": "string", "default": "sai_demo"}, "rainfall_mm_hr": {"type": "number", "default": 80}, "duration_min": {"type": "integer", "default": 120}}, "required": []}),
    Tool(name="calibrate_suggest", description="Suggest calibration parameter adjustments based on model performance", inputSchema={"type": "object", "properties": {"observed_peak_flow": {"type": "number", "default": 1.5}, "simulated_peak_flow": {"type": "number", "default": 2.0}, "nash_sutcliffe": {"type": "number", "default": 0.65}}, "required": []}),
]

HANDLERS = {"design_storm": design_storm, "runoff_compute": runoff_compute, "swmm_create_model": swmm_create_model, "swmm_simulate": swmm_simulate, "calibrate_suggest": calibrate_suggest}

mcp_server = Server("mcp-hydro")
sse = SseServerTransport("/messages/")
app = FastAPI(title="MCP Hydro Server")
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
    return {"status": "healthy", "server": "mcp-hydro", "tools": len(TOOLS)}


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    handler = HANDLERS.get(body.get("name"))
    if not handler:
        return {"error": f"Unknown tool: {body.get('name')}"}
    return await handler(**body.get("arguments", {}))


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=5005)


if __name__ == "__main__":
    main()
