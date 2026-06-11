from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, StreamingResponse

from app.config import DATA_DIR, GEN_TOOL_DIR, GLM_TOOLS, MCP_SERVERS, logger
from app.knowledge import get_weather, kg, rag, search_satellite
from app.store import conversations
from app.streaming import chat_stream_generator
from app.tracing import (
    evolution_suggestions, evolution_stats, get_all_traces, get_trace,
    log_routing, new_trace, twin,
)

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_IMG_DIR = DATA_DIR / "upload_images"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_IMG_DIR.mkdir(parents=True, exist_ok=True)


def register_routes(app):
    @app.get("/")
    async def index():
        resp = FileResponse(Path(__file__).parent.parent / "index.html")
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
                    results[name] = resp.json() if resp.status_code == 200 else {"status": "error", "code": resp.status_code}
                except Exception:
                    results[name] = {"status": "offline"}
        return results

    @app.post("/api/upload")
    async def upload_file(file: UploadFile = FastAPIFile(...)):
        dest = UPLOAD_DIR / file.filename
        content = await file.read()
        dest.write_bytes(content)
        info = {"filename": file.filename, "size": len(content), "path": str(dest)}
        ext = Path(file.filename).suffix.lower()
        if ext in (".geojson", ".json"):
            try:
                data = json.loads(content)
                if data.get("type") == "FeatureCollection":
                    info["format"] = "GeoJSON"
                    info["features"] = len(data.get("features", []))
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
    async def chat_stream(q: str, history: str = "", workflows: str = "", conv_id: int = 0):
        return StreamingResponse(
            chat_stream_generator(q, history, workflows, conv_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/upload_image")
    async def upload_image(file: UploadFile = FastAPIFile(...)):
        dest = UPLOAD_IMG_DIR / file.filename
        content = await file.read()
        dest.write_bytes(content)
        return {"filename": file.filename, "size": len(content), "path": str(dest)}

    @app.post("/api/analyze_image")
    async def analyze_image_api(image_base64: str = "", file_path: str = ""):
        from app.multimodal import analyze_image
        b64 = image_base64
        if not b64 and file_path:
            p = Path(file_path)
            if p.exists():
                b64 = __import__("base64").b64encode(p.read_bytes()).decode()
        if not b64:
            return {"error": "No image provided"}
        result = await analyze_image(b64)
        return {"analysis": result}

    @app.get("/api/memory")
    async def get_memory():
        from app.store import memory
        facts = [{"key": r[0], "value": r[1], "source": r[2]} for r in __import__("sqlite3").connect(str(DATA_DIR / "agent_memory.db")).execute("SELECT key,value,source FROM facts LIMIT 20").fetchall()]
        return {"facts": facts}

    @app.get("/api/weather")
    async def get_weather_api(lat: float = 33.19, lon: float = 104.89, days: int = 3):
        return await get_weather(lat, lon, days)

    @app.get("/api/satellite")
    async def get_satellite(date_start: str = "", date_end: str = ""):
        return await search_satellite(date_start=date_start, date_end=date_end)

    @app.get("/api/kg/entities")
    async def get_kg_entities(name: str = "", type: str = ""):
        return {"entities": kg.query_entities(name, type)}

    @app.get("/api/kg/relations")
    async def get_kg_relations(entity: str = ""):
        return {"relations": kg.query_relations(entity)}

    @app.get("/api/twin/sources")
    async def get_twin_sources():
        return {"sources": twin.list_sources()}

    @app.get("/api/twin/status")
    async def get_twin_status():
        return await twin.health_check()

    @app.get("/api/traces")
    async def get_traces():
        return {"traces": get_all_traces()}

    @app.get("/api/traces/{trace_id}")
    async def get_trace_api(trace_id: str):
        t = get_trace(trace_id)
        return t if t else {"error": "not found"}

    @app.get("/api/evolution/stats")
    async def get_evolution_stats():
        return evolution_stats()

    @app.get("/api/evolution/suggestions")
    async def get_evolution_suggestions():
        return {"suggestions": evolution_suggestions()}

    @app.get("/api/conversations")
    async def list_conversations():
        return {"conversations": conversations.list_conversations()}

    @app.post("/api/conversations")
    async def create_conversation(req: dict = None):
        title = (req or {}).get("title", "")
        cid = conversations.create_conversation(title)
        return {"id": cid}

    @app.get("/api/conversations/{conv_id}/messages")
    async def get_messages(conv_id: int):
        return {"messages": conversations.get_messages(conv_id)}

    @app.delete("/api/conversations/{conv_id}")
    async def delete_conversation(conv_id: int):
        conversations.delete_conversation(conv_id)
        return {"ok": True}

    @app.get("/api/rag/search")
    async def rag_search_api(q: str, limit: int = 5):
        return {"results": rag.search(q, limit)}

    @app.post("/api/rag/add")
    async def rag_add(req: dict):
        doc_id = rag.add_document(req.get("title", ""), req.get("content", ""), req.get("source", ""), req.get("tags", ""))
        return {"id": doc_id}
