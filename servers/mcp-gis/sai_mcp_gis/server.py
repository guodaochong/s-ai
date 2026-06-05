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

from sai_mcp_gis.tools.spatial_query import buffer, coordinate_transform, geometry_properties, overlay, spatial_query
from sai_mcp_gis.tools.vector_io import import_network, read_vector, write_vector

logger = structlog.get_logger(__name__)

TOOLS: list[Tool] = [
    Tool(
        name="spatial_query",
        description="Query spatial relationships between two geometries (intersects, contains, within, etc.)",
        inputSchema={
            "type": "object",
            "properties": {
                "geometry_a": {"type": "object", "description": "GeoJSON geometry"},
                "geometry_b": {"type": "object", "description": "GeoJSON geometry"},
                "relation": {"type": "string", "enum": ["intersects", "contains", "within", "touches", "crosses", "overlaps", "equals", "disjoint"], "default": "intersects"},
            },
            "required": ["geometry_a", "geometry_b"],
        },
    ),
    Tool(
        name="buffer",
        description="Create a buffer zone around a geometry",
        inputSchema={
            "type": "object",
            "properties": {
                "geometry": {"type": "object", "description": "GeoJSON geometry"},
                "distance": {"type": "number", "description": "Buffer distance", "default": 100.0},
                "unit": {"type": "string", "default": "meters"},
                "resolution": {"type": "integer", "default": 16},
            },
            "required": ["geometry"],
        },
    ),
    Tool(
        name="overlay",
        description="Geometric overlay operations (intersection, union, difference, symmetric_difference)",
        inputSchema={
            "type": "object",
            "properties": {
                "geometry_a": {"type": "object", "description": "GeoJSON geometry"},
                "geometry_b": {"type": "object", "description": "GeoJSON geometry"},
                "operation": {"type": "string", "enum": ["intersection", "union", "difference", "symmetric_difference"], "default": "intersection"},
            },
            "required": ["geometry_a", "geometry_b"],
        },
    ),
    Tool(
        name="coordinate_transform",
        description="Transform geometry coordinates between CRS (e.g. WGS84 to CGCS2000)",
        inputSchema={
            "type": "object",
            "properties": {
                "geometry": {"type": "object", "description": "GeoJSON geometry"},
                "source_crs": {"type": "string", "default": "EPSG:4326"},
                "target_crs": {"type": "string", "default": "EPSG:4490"},
            },
            "required": ["geometry"],
        },
    ),
    Tool(
        name="geometry_properties",
        description="Calculate geometry properties (area, perimeter, centroid, bounds, type)",
        inputSchema={
            "type": "object",
            "properties": {
                "geometry": {"type": "object", "description": "GeoJSON geometry"},
            },
            "required": ["geometry"],
        },
    ),
    Tool(
        name="read_vector",
        description="Read vector data from file (GeoJSON, Shapefile, GeoPackage)",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to vector file"},
                "layer": {"type": "string", "description": "Layer name (for GPKG)"},
                "bbox": {"type": "array", "items": {"type": "number"}, "description": "Bounding box [minx, miny, maxx, maxy]"},
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="write_vector",
        description="Write vector data to file",
        inputSchema={
            "type": "object",
            "properties": {
                "data": {"type": "object", "description": "GeoJSON FeatureCollection"},
                "file_path": {"type": "string", "description": "Output file path"},
                "driver": {"type": "string", "enum": ["GeoJSON", "ESRI Shapefile", "GPKG"], "default": "GeoJSON"},
            },
            "required": ["data", "file_path"],
        },
    ),
    Tool(
        name="import_network",
        description="Import pipe/drainage network from uploaded GIS file (GeoJSON, Shapefile, GPKG). Auto-detects geometry type and extracts network structure.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path to file"},
                "file_name": {"type": "string", "description": "Filename in uploads directory"},
                "network_type": {"type": "string", "enum": ["auto", "pipe_network", "nodes", "mixed"], "default": "auto"},
            },
            "required": [],
        },
    ),
]

HANDLERS: dict[str, Any] = {
    "spatial_query": spatial_query,
    "buffer": buffer,
    "overlay": overlay,
    "coordinate_transform": coordinate_transform,
    "geometry_properties": geometry_properties,
    "read_vector": read_vector,
    "write_vector": write_vector,
    "import_network": import_network,
}

mcp_server = Server("mcp-gis")
sse = SseServerTransport("/messages/")
app = FastAPI(title="MCP GIS Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    handler = HANDLERS.get(name)
    if handler is None:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    try:
        result = await handler(**arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
    except Exception as e:
        logger.exception("tool_error", tool=name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


@app.get("/health")
async def health():
    return {"status": "healthy", "server": "mcp-gis", "tools": len(TOOLS)}


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    name = body["name"]
    arguments = body.get("arguments", {})
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = await handler(**arguments)
        return result
    except Exception as e:
        logger.exception("tool_error_http", tool=name)
        return {"error": str(e)}


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=5001)


if __name__ == "__main__":
    main()
