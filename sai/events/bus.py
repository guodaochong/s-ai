from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any, Callable, Coroutine

import redis.asyncio as aioredis
import structlog

from sai.events.schemas import AgentEvent, EventType

logger = structlog.get_logger(__name__)

PUBSUB_PREFIX = "sai:bus"
ALL_EVENTS_CHANNEL = "sai:bus:all"


Handler = Callable[[AgentEvent], Coroutine[Any, Any, None]]


class _Subscription:
    def __init__(self, sub_id: str, handler: Handler, channels: set[str]) -> None:
        self.sub_id = sub_id
        self.handler = handler
        self.channels = channels


class EventBus:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client
        self._pubsub = redis_client.pubsub()
        self._subscriptions: dict[str, _Subscription] = {}
        self._channel_to_subs: dict[str, list[str]] = defaultdict(list)
        self._listener_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._pubsub.subscribe(ALL_EVENTS_CHANNEL)
        self._listener_task = asyncio.create_task(self._listen())
        logger.info("event_bus_started")

    async def stop(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        await self._pubsub.unsubscribe()
        await self._pubsub.aclose()
        logger.info("event_bus_stopped")

    async def publish(self, event: AgentEvent) -> None:
        payload = event.to_dict()
        message = __import__("json").dumps(payload, default=str)

        pipe = self._redis.pipeline(transaction=False)
        pipe.publish(ALL_EVENTS_CHANNEL, message)
        pipe.publish(f"{PUBSUB_PREFIX}:type:{event.event_type.value}", message)
        pipe.publish(f"{PUBSUB_PREFIX}:agent:{event.agent}", message)
        await pipe.execute()

    def subscribe(
        self,
        handler: Handler,
        event_types: list[EventType] | None = None,
        agent: str | None = None,
    ) -> str:
        sub_id = str(uuid.uuid4())
        channels: set[str] = set()

        if event_types:
            for et in event_types:
                channel = f"{PUBSUB_PREFIX}:type:{et.value}"
                channels.add(channel)
                self._channel_to_subs[channel].append(sub_id)
        if agent:
            channel = f"{PUBSUB_PREFIX}:agent:{agent}"
            channels.add(channel)
            self._channel_to_subs[channel].append(sub_id)

        if not channels:
            channels.add(ALL_EVENTS_CHANNEL)
            self._channel_to_subs[ALL_EVENTS_CHANNEL].append(sub_id)

        self._subscriptions[sub_id] = _Subscription(sub_id, handler, channels)
        logger.info("subscription_added", sub_id=sub_id, channels=list(channels))
        return sub_id

    async def unsubscribe(self, sub_id: str) -> None:
        sub = self._subscriptions.pop(sub_id, None)
        if sub is None:
            return
        for channel in sub.channels:
            subs = self._channel_to_subs.get(channel, [])
            if sub_id in subs:
                subs.remove(sub_id)

    async def _listen(self) -> None:
        async for message in self._pubsub.listen():
            if message["type"] != "message":
                continue

            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode()

            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode()

            try:
                payload = __import__("json").loads(data)
                event = AgentEvent.from_dict(payload)
            except Exception:
                logger.warning("invalid_event_message", channel=channel)
                continue

            await self._dispatch(channel, event)

    async def _dispatch(self, channel: str, event: AgentEvent) -> None:
        sub_ids = self._channel_to_subs.get(channel, [])
        all_ids = self._channel_to_subs.get(ALL_EVENTS_CHANNEL, [])
        targets = set(sub_ids + all_ids)

        for sid in targets:
            sub = self._subscriptions.get(sid)
            if sub is None:
                continue
            try:
                await sub.handler(event)
            except Exception:
                logger.exception(
                    "handler_error", sub_id=sid, event_type=event.event_type.value
                )
