from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from sai.events.schemas import AgentEvent, EventFilter

logger = structlog.get_logger(__name__)

EVENT_KEY_PREFIX = "sai:events"
TIMELINE_KEY = "sai:events:timeline"
AGENT_EVENTS_PREFIX = "sai:events:agent"


class EventStore:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def append(self, event: AgentEvent) -> str:
        event_key = f"{EVENT_KEY_PREFIX}:{event.event_id}"
        agent_key = f"{AGENT_EVENTS_PREFIX}:{event.agent}"

        pipe = self._redis.pipeline(transaction=False)
        pipe.json().set(event_key, "$", event.to_dict())
        pipe.zadd(TIMELINE_KEY, {event.event_id: event.timestamp.timestamp()})
        pipe.zadd(agent_key, {event.event_id: event.timestamp.timestamp()})
        await pipe.execute()

        logger.info(
            "event_stored",
            event_id=event.event_id,
            event_type=event.event_type.value,
            agent=event.agent,
        )
        return event.event_id

    async def get(self, event_id: str) -> AgentEvent | None:
        event_key = f"{EVENT_KEY_PREFIX}:{event_id}"
        data = await self._redis.json().get(event_key)
        if data is None:
            return None
        return AgentEvent.from_dict(data)

    async def query(self, filter: EventFilter) -> list[AgentEvent]:
        if filter.parent_event_id:
            return await self._query_by_parent(filter)

        min_score = filter.since.timestamp() if filter.since else "-inf"
        max_score = filter.until.timestamp() if filter.until else "+inf"

        source_key = (
            f"{AGENT_EVENTS_PREFIX}:{filter.agent}" if filter.agent else TIMELINE_KEY
        )

        raw_ids = await self._redis.zrevrangebyscore(
            source_key, max_score, min_score, start=0, num=filter.limit
        )
        event_ids = [eid if isinstance(eid, str) else eid.decode() for eid in raw_ids]

        events: list[AgentEvent] = []
        for eid in event_ids:
            event = await self.get(eid)
            if event is None:
                continue
            if filter.event_types and event.event_type not in filter.event_types:
                continue
            if filter.action and event.action != filter.action:
                continue
            events.append(event)

        return events

    async def _query_by_parent(self, filter: EventFilter) -> list[AgentEvent]:
        chain: list[AgentEvent] = []
        current_id: str | None = filter.parent_event_id

        while current_id and len(chain) < filter.limit:
            event = await self.get(current_id)
            if event is None:
                break
            chain.append(event)
            current_id = event.parent_event_id

        chain.reverse()
        return chain

    async def trace_backwards(self, event_id: str) -> list[AgentEvent]:
        return await self.query(
            EventFilter(parent_event_id=event_id, limit=1000)
        )

    async def get_agent_history(self, agent: str, limit: int = 50) -> list[AgentEvent]:
        return await self.query(EventFilter(agent=agent, limit=limit))

    async def delete(self, event_id: str) -> bool:
        event = await self.get(event_id)
        if event is None:
            return False

        pipe = self._redis.pipeline(transaction=False)
        pipe.delete(f"{EVENT_KEY_PREFIX}:{event_id}")
        pipe.zrem(TIMELINE_KEY, event_id)
        pipe.zrem(f"{AGENT_EVENTS_PREFIX}:{event.agent}", event_id)
        await pipe.execute()
        return True
