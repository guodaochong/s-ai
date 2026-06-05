from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
import structlog

from sai.events.schemas import BlackboardEntry

logger = structlog.get_logger(__name__)

BLACKBOARD_PREFIX = "sai:blackboard"
VERSION_PREFIX = "sai:blackboard:version"


class Blackboard:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def write(
        self,
        key: str,
        value: Any,
        producer: str,
        ttl_seconds: int | None = None,
    ) -> int:
        entry_key = f"{BLACKBOARD_PREFIX}:{key}"
        version_key = f"{VERSION_PREFIX}:{key}"

        version = await self._redis.incr(version_key)

        payload = {
            "key": key,
            "value": value,
            "producer_agent": producer,
            "timestamp": datetime.utcnow().isoformat(),
            "ttl_seconds": ttl_seconds,
            "version": version,
        }

        pipe = self._redis.pipeline(transaction=False)
        pipe.json().set(entry_key, "$", payload)
        if ttl_seconds is not None:
            pipe.expire(entry_key, ttl_seconds)
            pipe.expire(version_key, ttl_seconds)
        await pipe.execute()

        logger.info(
            "blackboard_write", key=key, producer=producer, version=version
        )
        return version

    async def read(self, key: str) -> BlackboardEntry | None:
        entry_key = f"{BLACKBOARD_PREFIX}:{key}"
        data = await self._redis.json().get(entry_key)
        if data is None:
            return None
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return BlackboardEntry(**data)

    async def query(self, pattern: str = "*") -> list[BlackboardEntry]:
        keys = await self._redis.keys(f"{BLACKBOARD_PREFIX}:{pattern}")
        entries: list[BlackboardEntry] = []
        for raw_key in keys:
            key = raw_key if isinstance(raw_key, str) else raw_key.decode()
            data = await self._redis.json().get(key)
            if data is None:
                continue
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
            entries.append(BlackboardEntry(**data))
        return entries

    async def delete(self, key: str) -> bool:
        entry_key = f"{BLACKBOARD_PREFIX}:{key}"
        version_key = f"{VERSION_PREFIX}:{key}"
        pipe = self._redis.pipeline(transaction=False)
        pipe.delete(entry_key)
        pipe.delete(version_key)
        results = await pipe.execute()
        return results[0] > 0

    async def list_keys(self, prefix: str = "") -> list[str]:
        pattern = f"{BLACKBOARD_PREFIX}:{prefix}*" if prefix else f"{BLACKBOARD_PREFIX}:*"
        raw_keys = await self._redis.keys(pattern)
        keys: list[str] = []
        for rk in raw_keys:
            k = rk if isinstance(rk, str) else rk.decode()
            keys.append(k.removeprefix(f"{BLACKBOARD_PREFIX}:"))
        return sorted(keys)
