"""S-AI Web API — Spatial Intelligence Platform for Water Resources Engineering.

A FastAPI application that orchestrates LLM reasoning (GLM-4), MCP microservices
(7 specialized servers), and spatial visualization (Three.js / Leaflet) for
natural-language-driven hydrology and GIS analysis.

Architecture:
    server.py          → Application factory (create_app) + uvicorn entry point
    app/streaming.py   → SSE chat endpoint with ReAct reasoning loop
    app/dispatcher.py  → Internal tool dispatch via dict-based handler registry
    app/tools/         → LLM-powered code generation sandbox
    app/routes/        → REST API routers (system, files, data, tracing, reconstruct)

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import AuthMiddleware
from app.routes import conversations, data, files, reconstruct, system, tracing
from app.streaming import router as chat_router

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

load_dotenv(Path(__file__).parent.parent / ".env")


def create_app() -> FastAPI:
    """Application factory: configure middleware, mount static assets, register routers."""
    app = FastAPI(title="S-AI Web API", author=__author__)

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(AuthMiddleware)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    for r in (system, files, data, tracing, reconstruct, conversations):
        app.include_router(r.router)
    app.include_router(chat_router)

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
