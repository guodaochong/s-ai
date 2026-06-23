"""Tracing routes — execution traces and evolution statistics.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter

from app.tracing import evolution_stats, evolution_suggestions, get_all_traces, get_trace

router = APIRouter()


@router.get("/api/traces")
async def get_traces():
    return {"traces": get_all_traces()[:20]}


@router.get("/api/traces/{trace_id}")
async def get_trace_api(trace_id: str):
    result = get_trace(trace_id)
    return result if result else {"error": "not found"}


@router.get("/api/evolution/stats")
async def get_evolution_stats():
    return evolution_stats()


@router.get("/api/evolution/suggestions")
async def get_evolution_suggestions():
    return {"suggestions": evolution_suggestions()}
