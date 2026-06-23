"""Data query routes — weather, satellite, knowledge graph, digital twin, memory.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter

from app.knowledge import get_weather, kg, search_satellite
from app.store import MemoryStore
from app.tracing import twin

router = APIRouter()
_memory = MemoryStore()


@router.get("/api/memory")
async def get_memory():
    facts = _memory.recall_facts()
    procedures = _memory.recall_procedures("", limit=10)
    return {"facts": facts, "procedures": procedures}


@router.get("/api/weather")
async def get_weather_api(lat: float = 33.19, lon: float = 104.89, days: int = 3):
    return await get_weather(lat, lon, days)


@router.get("/api/satellite")
async def get_satellite(date_start: str = "", date_end: str = ""):
    return await search_satellite(date_start=date_start, date_end=date_end)


@router.get("/api/kg/entities")
async def get_kg_entities(name: str = "", type: str = ""):
    return {"entities": kg.query_entities(name, type)}


@router.get("/api/kg/relations")
async def get_kg_relations(entity: str = ""):
    return {"relations": kg.query_relations(entity)}


@router.get("/api/twin/sources")
async def get_twin_sources():
    return {"sources": twin.list_sources()}


@router.get("/api/twin/status")
async def get_twin_status():
    return {"status": await twin.health_check()}
