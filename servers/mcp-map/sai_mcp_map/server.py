from __future__ import annotations

import base64
import io
import json
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

logger = structlog.get_logger(__name__)


def _fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    plt.close(fig)
    return b64


async def render_map(
    layers: list[dict[str, Any]],
    title: str = "Map",
    basemap: str = "osm",
    width: int = 1200,
    height: int = 800,
) -> dict[str, Any]:
    fig, ax = plt.subplots(1, 1, figsize=(width / 100, height / 100))

    for layer in layers:
        data = layer.get("data", {})
        style = layer.get("style", {})
        geom_type = _detect_geom_type(data)

        if geom_type == "Point":
            coords = _extract_coords(data)
            ax.scatter([c[0] for c in coords], [c[1] for c in coords],
                       c=style.get("color", "red"), s=style.get("size", 20), alpha=0.7)
        elif geom_type in ("Polygon", "MultiPolygon"):
            for feat in data.get("features", []):
                from shapely.geometry import shape
                geom = shape(feat.get("geometry", {}))
                x, y = geom.exterior.xy if hasattr(geom, "exterior") else ([], [])
                ax.fill(x, y, alpha=style.get("alpha", 0.3), color=style.get("color", "blue"))
                ax.plot(x, y, color=style.get("edge_color", "black"), linewidth=0.5)
        elif geom_type in ("LineString", "MultiLineString"):
            for feat in data.get("features", []):
                from shapely.geometry import shape
                geom = shape(feat.get("geometry", {}))
                x, y = geom.xy
                ax.plot(x, y, color=style.get("color", "blue"), linewidth=style.get("width", 1))

    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    return {"image_base64": _fig_to_base64(fig), "format": "png", "title": title}


async def create_choropleth(
    data: dict[str, Any],
    value_field: str,
    classification: str = "quantiles",
    num_classes: int = 5,
    colormap: str = "YlOrRd",
    title: str = "Thematic Map",
) -> dict[str, Any]:
    fig, ax = plt.subplots(1, 1, figsize=(12, 8))
    features = data.get("features", [])

    values = [f.get("properties", {}).get(value_field, 0) for f in features]
    if not values:
        return {"error": "No features with the specified value_field"}

    vmin, vmax = min(values), max(values)
    cmap = plt.get_cmap(colormap)

    for feat, val in zip(features, values):
        from shapely.geometry import shape
        geom = shape(feat.get("geometry", {}))
        normalized = (val - vmin) / (vmax - vmin) if vmax > vmin else 0.5
        color = cmap(normalized)

        if hasattr(geom, "exterior"):
            x, y = geom.exterior.xy
            ax.fill(x, y, color=color, edgecolor="black", linewidth=0.3)
        elif geom.geom_type == "MultiPolygon":
            for poly in geom.geoms:
                x, y = poly.exterior.xy
                ax.fill(x, y, color=color, edgecolor="black", linewidth=0.3)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
    sm.set_array([])
    plt.colorbar(sm, ax=ax, label=value_field)
    ax.set_title(title)

    return {"image_base64": _fig_to_base64(fig), "format": "png", "title": title}


async def plot_timeseries(
    data: list[dict[str, Any]],
    label: str = "Value",
    ylabel: str = "Value",
    title: str = "Time Series",
) -> dict[str, Any]:
    fig, ax = plt.subplots(1, 1, figsize=(14, 6))

    timestamps = [d.get("timestamp", i) for i, d in enumerate(data)]
    values = [d.get("value", 0) for d in data]

    ax.plot(range(len(values)), values, "b-", linewidth=1.5, label=label)
    ax.fill_between(range(len(values)), values, alpha=0.1)
    ax.set_xlabel("Time")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)

    n_labels = min(10, len(timestamps))
    if n_labels > 0:
        step = max(1, len(timestamps) // n_labels)
        tick_positions = list(range(0, len(timestamps), step))
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([str(timestamps[i]) for i in tick_positions], rotation=45, ha="right")

    return {"image_base64": _fig_to_base64(fig), "format": "png", "title": title}


async def export_geojson(data: dict[str, Any], properties_to_include: list[str] | None = None) -> dict[str, Any]:
    if properties_to_include:
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            feat["properties"] = {k: v for k, v in props.items() if k in properties_to_include}
    return {"geojson": json.dumps(data, ensure_ascii=False)}


def _detect_geom_type(data: dict[str, Any]) -> str:
    for feat in data.get("features", []):
        geom = feat.get("geometry", {})
        gt = geom.get("type", "")
        if gt:
            return gt
    return "Unknown"


def _extract_coords(data: dict[str, Any]) -> list[list[float]]:
    coords: list[list[float]] = []
    for feat in data.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") == "Point":
            coords.append(geom.get("coordinates", []))
    return coords


mcp_server = Server("mcp-map")
sse = SseServerTransport("/messages/")
app = FastAPI(title="MCP Map Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TOOLS = [
    Tool(name="render_map", description="Render a static map from GeoJSON layers", inputSchema={"type": "object", "properties": {"layers": {"type": "array", "items": {"type": "object"}}, "title": {"type": "string", "default": "Map"}, "width": {"type": "integer", "default": 1200}, "height": {"type": "integer", "default": 800}}, "required": ["layers"]}),
    Tool(name="create_choropleth", description="Create a choropleth thematic map", inputSchema={"type": "object", "properties": {"data": {"type": "object"}, "value_field": {"type": "string"}, "colormap": {"type": "string", "default": "YlOrRd"}, "title": {"type": "string", "default": "Thematic Map"}}, "required": ["data", "value_field"]}),
    Tool(name="plot_timeseries", description="Plot time series data (water level, flow, rainfall)", inputSchema={"type": "object", "properties": {"data": {"type": "array", "items": {"type": "object"}}, "label": {"type": "string", "default": "Value"}, "ylabel": {"type": "string", "default": "Value"}, "title": {"type": "string", "default": "Time Series"}}, "required": ["data"]}),
    Tool(name="export_geojson", description="Export data as GeoJSON", inputSchema={"type": "object", "properties": {"data": {"type": "object"}, "properties_to_include": {"type": "array", "items": {"type": "string"}}}, "required": ["data"]}),
]

HANDLERS = {"render_map": render_map, "create_choropleth": create_choropleth, "plot_timeseries": plot_timeseries, "export_geojson": export_geojson}


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
    return {"status": "healthy", "server": "mcp-map", "tools": len(TOOLS)}


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    handler = HANDLERS.get(body["name"])
    if not handler:
        return {"error": f"Unknown tool: {body['name']}"}
    return await handler(**body.get("arguments", {}))


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=5004)


if __name__ == "__main__":
    main()
