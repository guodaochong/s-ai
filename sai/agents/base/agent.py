from __future__ import annotations

import asyncio
import json
import traceback
from abc import ABC, abstractmethod
from typing import Any

import redis.asyncio as aioredis
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

from sai.agents.base.config import AgentConfig
from sai.agents.base.lifecycle import AgentState, LifecycleManager
from sai.events.blackboard import Blackboard
from sai.events.bus import EventBus
from sai.events.schemas import AgentEvent, EventType
from sai.events.store import EventStore
from sai.llm.client import GLMClient
from sai.llm.types import LLMResponse, Message, MessageRole, ToolDefinition

logger = structlog.get_logger(__name__)


class SpatialAgent(ABC):
    def __init__(
        self,
        config: AgentConfig,
        llm_client: GLMClient,
        redis_url: str = "redis://localhost:6379/0",
        registry_url: str = "http://localhost:9000",
    ) -> None:
        self._config = config
        self._llm = llm_client
        self._registry_url = registry_url
        self._redis_url = redis_url

        self._lifecycle = LifecycleManager(config.name, config.max_concurrent_tasks)
        self._mcp_server = Server(f"agent-{config.name}")
        self._app = FastAPI(title=f"Agent {config.name}")
        self._sse = SseServerTransport("/messages/")

        self._redis: aioredis.Redis | None = None
        self._event_store: EventStore | None = None
        self._event_bus: EventBus | None = None
        self._blackboard: Blackboard | None = None

        self._tool_clients: dict[str, Any] = {}
        self._heartbeat_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def lifecycle(self) -> LifecycleManager:
        return self._lifecycle

    @abstractmethod
    def register_tools(self) -> list[ToolDefinition]:
        ...

    @abstractmethod
    async def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> Any:
        ...

    @abstractmethod
    def get_system_prompt(self) -> str:
        ...

    async def start(self) -> None:
        self._lifecycle.transition(AgentState.INITIALIZING)

        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        self._event_store = EventStore(self._redis)
        self._event_bus = EventBus(self._redis)
        self._blackboard = Blackboard(self._redis)

        await self._event_bus.start()
        logger.info("event_system_connected", agent=self.name)

        await self._connect_tool_servers()
        logger.info("tool_servers_connected", agent=self.name)

        self._setup_mcp_server()
        self._setup_fastapi()

        await self._register_with_registry()

        self._lifecycle.transition(AgentState.READY)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info(
            "agent_started",
            agent=self.name,
            port=self._config.port,
            capabilities=self._config.capabilities,
        )

        config = uvicorn.Config(
            self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self) -> None:
        self._lifecycle.transition(AgentState.STOPPING)

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._event_bus:
            await self._event_bus.stop()
        if self._redis:
            await self._redis.aclose()

        await self._llm.close()

        await self._deregister_from_registry()

        self._lifecycle.transition(AgentState.STOPPED)
        logger.info("agent_stopped", agent=self.name)

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not self._lifecycle.should_accept_task():
            raise RuntimeError(f"Agent {self.name} cannot accept tasks in state {self._lifecycle.state}")

        self._lifecycle.record_task_start()
        parent_id: str | None = None

        try:
            event = AgentEvent(
                event_type=EventType.TOOL_CALLED,
                agent=self.name,
                action=f"{server_name}.{tool_name}",
                input=arguments,
                parent_event_id=parent_id,
            )
            if self._event_store:
                event_id = await self._event_store.append(event)
                parent_id = event_id

            import httpx
            server_url = self._resolve_server_url(server_name)
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{server_url}/call_tool",
                    json={"name": tool_name, "arguments": arguments},
                )
                resp.raise_for_status()
                result = resp.json()

            if self._event_store:
                await self._event_store.append(AgentEvent(
                    event_type=EventType.TOOL_RESULT,
                    agent=self.name,
                    action=f"{server_name}.{tool_name}",
                    output=result,
                    parent_event_id=parent_id,
                ))

            return result

        except Exception as e:
            logger.exception("tool_call_failed", agent=self.name, server=server_name, tool=tool_name)
            if self._event_store:
                await self._event_store.append(AgentEvent(
                    event_type=EventType.ERROR,
                    agent=self.name,
                    action=f"{server_name}.{tool_name}",
                    output={"error": str(e)},
                    parent_event_id=parent_id,
                ))
            raise
        finally:
            self._lifecycle.record_task_complete()

    async def call_agent(self, agent_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        import httpx

        agent_url = await self._resolve_agent_url(agent_name)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{agent_url}/call_tool",
                json={"name": tool_name, "arguments": arguments},
            )
            resp.raise_for_status()
            result = resp.json()

        if self._event_store:
            await self._event_store.append(AgentEvent(
                event_type=EventType.AGENT_COLLAB,
                agent=self.name,
                action=f"call:{agent_name}.{tool_name}",
                input=arguments,
                output=result,
            ))

        return result

    async def reason(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> LLMResponse:
        system_msg = Message(role=MessageRole.SYSTEM, content=self.get_system_prompt())
        full_messages = [system_msg] + messages

        response = await self._llm.chat(full_messages, tools=tools)

        if self._event_store:
            await self._event_store.append(AgentEvent(
                event_type=EventType.TASK_STARTED,
                agent=self.name,
                action="llm_reasoning",
                output={"content": response.content, "tool_calls": len(response.tool_calls)},
            ))

        return response

    async def write_to_blackboard(self, key: str, value: Any, ttl: int | None = None) -> int:
        if not self._blackboard:
            raise RuntimeError("Blackboard not initialized")
        version = await self._blackboard.write(key, value, producer=self.name, ttl_seconds=ttl)
        if self._event_store:
            await self._event_store.append(AgentEvent(
                event_type=EventType.DATA_PRODUCED,
                agent=self.name,
                action=f"blackboard_write:{key}",
                output={"version": version},
            ))
        return version

    async def read_from_blackboard(self, key: str) -> Any:
        if not self._blackboard:
            raise RuntimeError("Blackboard not initialized")
        entry = await self._blackboard.read(key)
        if entry is None:
            return None
        if self._event_store:
            await self._event_store.append(AgentEvent(
                event_type=EventType.DATA_CONSUMED,
                agent=self.name,
                action=f"blackboard_read:{key}",
            ))
        return entry.value

    def _setup_mcp_server(self) -> None:
        tool_defs = self.register_tools()

        @self._mcp_server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name=td.name,
                    description=td.description,
                    inputSchema=td.parameters,
                )
                for td in tool_defs
            ]

        @self._mcp_server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            try:
                result = await self.handle_tool_call(name, arguments)
                content = json.dumps(result, ensure_ascii=False, default=str) if not isinstance(result, str) else result
                return [TextContent(type="text", text=content)]
            except Exception as e:
                return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]

    def _setup_fastapi(self) -> None:
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self._app.get("/health")(self._health_endpoint)
        self._app.post("/call_tool")(self._call_tool_endpoint)

        self._app.router.add_api_route(
            "/sse",
            self._sse.connect_sse,
            methods=["GET"],
        )
        self._app.router.add_api_route(
            "/messages/",
            self._sse.handle_post_message,
            methods=["POST"],
        )

    async def _health_endpoint(self) -> dict[str, Any]:
        status = self._lifecycle.status
        return {
            "agent": self.name,
            "state": status.state.value,
            "uptime": status.uptime,
            "tasks_completed": status.tasks_completed,
            "tasks_failed": status.tasks_failed,
            "current_load": status.current_load,
        }

    async def _call_tool_endpoint(self, body: dict[str, Any]) -> Any:
        name = body["name"]
        arguments = body.get("arguments", {})
        result = await self.handle_tool_call(name, arguments)
        return result

    async def _connect_tool_servers(self) -> None:
        for ts in self._config.tool_servers:
            self._tool_clients[ts.name] = ts.url
            logger.info("tool_server_registered", name=ts.name, url=ts.url)

    def _resolve_server_url(self, server_name: str) -> str:
        if server_name in self._tool_clients:
            return self._tool_clients[server_name]
        name_to_url = {
            "mcp-gis": f"http://localhost:5001",
            "mcp-data": f"http://localhost:5002",
            "mcp-knowledge": f"http://localhost:5003",
            "mcp-map": f"http://localhost:5004",
            "mcp-hydro": f"http://localhost:5005",
            "mcp-flood": f"http://localhost:5006",
            "mcp-raster": f"http://localhost:5007",
        }
        url = name_to_url.get(server_name)
        if url:
            return url
        raise ValueError(f"Unknown tool server: {server_name}")

    async def _resolve_agent_url(self, agent_name: str) -> str:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._registry_url}/agents/{agent_name}")
                if resp.status_code == 200:
                    return resp.json()["url"]
        except Exception:
            pass
        agent_ports: dict[str, str] = {
            "router": "http://localhost:6000",
            "gis": "http://localhost:6001",
            "hydro": "http://localhost:6002",
            "flood": "http://localhost:6003",
            "data": "http://localhost:6004",
            "knowledge": "http://localhost:6005",
            "report": "http://localhost:6006",
        }
        url = agent_ports.get(agent_name)
        if url:
            return url
        raise ValueError(f"Unknown agent: {agent_name}")

    async def _register_with_registry(self) -> None:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{self._registry_url}/register",
                    json={
                        "name": self.name,
                        "url": f"http://agent-{self.name}:{self._config.port}",
                        "capabilities": self._config.capabilities,
                        "tools_exposed": [t.name for t in self.register_tools()],
                        "dependencies": [ts.name for ts in self._config.tool_servers],
                        "status": "healthy",
                    },
                )
            logger.info("registered_with_registry", agent=self.name)
        except Exception:
            logger.warning("registry_registration_failed", agent=self.name)

    async def _deregister_from_registry(self) -> None:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.delete(f"{self._registry_url}/register/{self.name}")
        except Exception:
            pass

    async def _heartbeat_loop(self) -> None:
        while self._lifecycle.state not in {AgentState.STOPPING, AgentState.STOPPED}:
            try:
                self._lifecycle.heartbeat()
                import httpx
                async with httpx.AsyncClient(timeout=3.0) as client:
                    await client.put(
                        f"{self._registry_url}/agents/{self.name}/heartbeat",
                        json={
                            "load": self._lifecycle.status.current_load,
                            "state": self._lifecycle.state.value,
                        },
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("heartbeat_failed", agent=self.name)
            await asyncio.sleep(self._config.health_check_interval)
