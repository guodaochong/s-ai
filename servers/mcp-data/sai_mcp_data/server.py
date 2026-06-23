from __future__ import annotations

import json
import re
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

logger = structlog.get_logger(__name__)

mcp_server = Server("mcp-data")
sse = SseServerTransport("/messages/")
app = FastAPI(title="MCP Data Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_DANGEROUS_PATTERNS = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT)\b", re.IGNORECASE)


async def import_data(
    data: dict[str, Any],
    table_name: str,
    srid: int = 4490,
    overwrite: bool = False,
) -> dict[str, Any]:
    feature_count = len(data.get("features", []))
    bounds = _extract_bounds(data)
    return {
        "status": "imported",
        "table_name": table_name,
        "row_count": feature_count,
        "bounds": bounds,
        "srid": srid,
        "overwrite": overwrite,
    }


async def query_spatial(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if _DANGEROUS_PATTERNS.search(sql):
        raise ValueError("Only SELECT statements are allowed")
    return {
        "sql": sql,
        "params": params,
        "results": [],
        "row_count": 0,
        "note": "Connect to PostGIS for production queries",
    }


async def query_by_geometry(
    table_name: str,
    geometry: dict[str, Any],
    relation: str = "intersects",
    limit: int = 100,
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [],
        "table_name": table_name,
        "relation": relation,
        "limit": limit,
        "note": "Connect to PostGIS for production queries",
    }


async def validate_data(data: dict[str, Any], checks: list[str] | None = None) -> dict[str, Any]:
    checks = checks or ["topology", "attributes", "crs"]
    features = data.get("features", [])
    issues: list[dict[str, Any]] = []

    if "attributes" in checks:
        for i, feat in enumerate(features):
            if "properties" not in feat:
                issues.append({"feature_index": i, "check": "attributes", "issue": "missing properties"})
            elif not feat["properties"]:
                issues.append({"feature_index": i, "check": "attributes", "issue": "empty properties"})

    if "crs" in checks:
        if "crs" not in data:
            issues.append({"check": "crs", "issue": "no CRS specified, assuming EPSG:4326"})

    if "topology" in checks:
        from shapely.geometry import shape
        for i, feat in enumerate(features):
            geom = feat.get("geometry")
            if geom:
                try:
                    shapely_geom = shape(geom)
                    if not shapely_geom.is_valid:
                        issues.append({"feature_index": i, "check": "topology", "issue": "invalid geometry"})
                except Exception as e:
                    issues.append({"feature_index": i, "check": "topology", "issue": str(e)})

    return {
        "feature_count": len(features),
        "checks_performed": checks,
        "issues_found": len(issues),
        "issues": issues,
        "is_valid": len(issues) == 0,
    }


async def list_tables() -> dict[str, Any]:
    return {
        "tables": [],
        "note": "Connect to PostGIS for production table listing",
    }


def _extract_bounds(data: dict[str, Any]) -> list[float] | None:
    features = data.get("features", [])
    if not features:
        return None
    from shapely.geometry import shape
    bounds = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        try:
            b = shape(geom).bounds
            bounds[0] = min(bounds[0], b[0])
            bounds[1] = min(bounds[1], b[1])
            bounds[2] = max(bounds[2], b[2])
            bounds[3] = max(bounds[3], b[3])
        except Exception as exc:
            logger.warning("[Data] geometry bounds extraction failed", error=str(exc)[:200])
    return bounds if bounds[0] != float("inf") else None


TOOLS = [
    Tool(name="import_data", description="Import spatial data into PostGIS", inputSchema={"type": "object", "properties": {"data": {"type": "object", "description": "GeoJSON FeatureCollection"}, "table_name": {"type": "string"}, "srid": {"type": "integer", "default": 4490}, "overwrite": {"type": "boolean", "default": False}}, "required": ["data", "table_name"]}),
    Tool(name="query_spatial", description="Execute spatial SQL query (SELECT only)", inputSchema={"type": "object", "properties": {"sql": {"type": "string"}, "params": {"type": "object"}}, "required": ["sql"]}),
    Tool(name="query_by_geometry", description="Query features by geometry relationship", inputSchema={"type": "object", "properties": {"table_name": {"type": "string"}, "geometry": {"type": "object"}, "relation": {"type": "string", "default": "intersects"}, "limit": {"type": "integer", "default": 100}}, "required": ["table_name", "geometry"]}),
    Tool(name="validate_data", description="Validate spatial data quality", inputSchema={"type": "object", "properties": {"data": {"type": "object", "description": "GeoJSON FeatureCollection"}, "checks": {"type": "array", "items": {"type": "string", "enum": ["topology", "attributes", "crs"]}}}, "required": ["data"]}),
    Tool(name="list_tables", description="List spatial tables in database", inputSchema={"type": "object", "properties": {}}),
]

HANDLERS = {
    "import_data": import_data,
    "query_spatial": query_spatial,
    "query_by_geometry": query_by_geometry,
    "validate_data": validate_data,
    "list_tables": list_tables,
}


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
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


@app.get("/health")
async def health():
    return {"status": "healthy", "server": "mcp-data", "tools": len(TOOLS)}


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    handler = HANDLERS.get(body["name"])
    if not handler:
        return {"error": f"Unknown tool: {body['name']}"}
    try:
        return await handler(**body.get("arguments", {}))
    except Exception as e:
        return {"error": str(e)}


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=5002)


if __name__ == "__main__":
    main()
