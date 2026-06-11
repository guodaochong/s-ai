from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api import register_routes

app = FastAPI(title="S-AI Web API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

register_routes(app)

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=3000, reload=False)
