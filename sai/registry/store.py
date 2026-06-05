from __future__ import annotations

from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

REGISTRY_KEY = "sai:registry:agents"
AGENT_DATA_PREFIX = "sai:registry:agent"


class AgentRegistration(BaseModel):
    name: str
    url: str
    capabilities: list[str] = []
    tools_exposed: list[str] = []
    dependencies: list[str] = []
    status: str = "healthy"
    registered_at: str = ""
    last_heartbeat: str = ""
    current_load: float = 0.0
    metadata: dict[str, Any] = {}


class RegistryStore:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def register(self, reg: AgentRegistration) -> None:
        now = datetime.utcnow().isoformat()
        if not reg.registered_at:
            reg.registered_at = now
        reg.last_heartbeat = now

        data = reg.model_dump_json()
        pipe = self._redis.pipeline(transaction=False)
        pipe.hset(REGISTRY_KEY, reg.name, data)
        pipe.json().set(f"{AGENT_DATA_PREFIX}:{reg.name}", "$", reg.model_dump())
        await pipe.execute()
        logger.info("agent_registered", name=reg.name, url=reg.url)

    async def deregister(self, name: str) -> bool:
        pipe = self._redis.pipeline(transaction=False)
        pipe.hdel(REGISTRY_KEY, name)
        pipe.delete(f"{AGENT_DATA_PREFIX}:{name}")
        result = await pipe.execute()
        deregistered = result[0] > 0
        if deregistered:
            logger.info("agent_deregistered", name=name)
        return deregistered

    async def get(self, name: str) -> AgentRegistration | None:
        data = await self._redis.hget(REGISTRY_KEY, name)
        if data is None:
            return None
        raw = data if isinstance(data, str) else data.decode()
        return AgentRegistration.model_validate_json(raw)

    async def list_all(self) -> list[AgentRegistration]:
        raw = await self._redis.hgetall(REGISTRY_KEY)
        agents: list[AgentRegistration] = []
        for val in raw.values():
            s = val if isinstance(val, str) else val.decode()
            agents.append(AgentRegistration.model_validate_json(s))
        return agents

    async def find_by_capability(self, capability: str) -> list[AgentRegistration]:
        all_agents = await self.list_all()
        matching = [a for a in all_agents if capability in a.capabilities and a.status == "healthy"]
        matching.sort(key=lambda a: a.current_load)
        return matching

    async def find_by_tool(self, tool_name: str) -> list[AgentRegistration]:
        all_agents = await self.list_all()
        matching = [a for a in all_agents if tool_name in a.tools_exposed and a.status == "healthy"]
        matching.sort(key=lambda a: a.current_load)
        return matching

    async def update_heartbeat(self, name: str, load: float = 0.0, state: str = "healthy") -> None:
        reg = await self.get(name)
        if reg is None:
            return
        reg.last_heartbeat = datetime.utcnow().isoformat()
        reg.current_load = load
        reg.status = "healthy" if state in {"ready", "busy"} else state
        await self.register(reg)

    async def cleanup_stale(self, timeout_seconds: int = 60) -> int:
        all_agents = await self.list_all()
        now = datetime.utcnow()
        removed = 0
        for agent in all_agents:
            try:
                hb = datetime.fromisoformat(agent.last_heartbeat)
                if (now - hb).total_seconds() > timeout_seconds:
                    agent.status = "unhealthy"
                    await self.register(agent)
                    removed += 1
            except (ValueError, TypeError):
                pass
        if removed > 0:
            logger.info("stale_agents_cleaned", count=removed)
        return removed
