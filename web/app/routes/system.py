"""System routes — index page, health check, MCP server status, heightmap proxy.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import APIRouter
from starlette.responses import FileResponse

from app.config import GLM_TOOLS, MCP_SERVERS

router = APIRouter()


@router.get("/")
async def index():
    resp = FileResponse(Path(__file__).parent.parent.parent / "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "web", "engine": "react-fc-v2", "tools": len(GLM_TOOLS)}


@router.get("/api/servers")
async def list_servers():
    results: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in MCP_SERVERS.items():
            try:
                resp = await client.get(f"{url}/health")
                results[name] = {"url": url, "status": "healthy", "info": resp.json()}
            except Exception:
                results[name] = {"url": url, "status": "offline", "info": None}
    return results


@router.get("/api/heightmap")
async def heightmap_proxy(size: int = 256):
    raster_url = MCP_SERVERS.get("raster", "http://127.0.0.1:5007")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{raster_url}/api/heightmap", params={"size": size})
        return resp.json()
