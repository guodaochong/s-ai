"""Conversation history REST API — list, create, delete, load messages.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter

from app.store import ConversationStore

router = APIRouter()
_store = ConversationStore()


@router.get("/api/conversations")
async def list_conversations():
    return {"conversations": _store.list_conversations()}


@router.post("/api/conversations")
async def create_conversation(body: dict = None):
    title = (body or {}).get("title", "")
    conv_id = _store.create_conversation(title)
    return {"id": conv_id, "title": title or "新对话"}


@router.get("/api/conversations/{conv_id}/messages")
async def get_messages(conv_id: int):
    return {"messages": _store.get_messages(conv_id)}


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: int):
    _store.delete_conversation(conv_id)
    return {"ok": True}
