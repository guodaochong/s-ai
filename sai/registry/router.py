from __future__ import annotations

from sai.registry.store import AgentRegistration, RegistryStore


class CapabilityRouter:
    def __init__(self, store: RegistryStore) -> None:
        self._store = store

    async def find_best_agent(
        self,
        required_capabilities: list[str],
        exclude: list[str] | None = None,
    ) -> AgentRegistration | None:
        exclude = exclude or []
        all_agents = await self._store.list_all()
        candidates: list[tuple[int, AgentRegistration]] = []

        for agent in all_agents:
            if agent.name in exclude:
                continue
            if agent.status != "healthy":
                continue
            matched = sum(1 for cap in required_capabilities if cap in agent.capabilities)
            if matched == len(required_capabilities):
                candidates.append((matched, agent))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], -x[1].current_load))
        return candidates[0][1]

    async def find_agents_for_task(self, task_description: str) -> list[AgentRegistration]:
        all_agents = await self._store.list_all()
        keywords = set(task_description.lower().split())
        scored: list[tuple[float, AgentRegistration]] = []

        for agent in all_agents:
            if agent.status != "healthy":
                continue
            agent_text = " ".join(agent.capabilities + agent.tools_exposed).lower()
            overlap = len(keywords & set(agent_text.split()))
            if overlap > 0:
                scored.append((overlap, agent))

        scored.sort(key=lambda x: (-x[0], x[1].current_load))
        return [a for _, a in scored]

    async def resolve_tool_server(self, tool_name: str) -> AgentRegistration | None:
        results = await self._store.find_by_tool(tool_name)
        return results[0] if results else None
