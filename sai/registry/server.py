from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sai.config import settings
from sai.registry.router import CapabilityRouter
from sai.registry.store import AgentRegistration, RegistryStore

logger = structlog.get_logger(__name__)

redis_client: aioredis.Redis | None = None
store: RegistryStore | None = None
router: CapabilityRouter | None = None
cleanup_task: asyncio.Task[None] | None = None


class RegisterRequest(BaseModel):
    name: str
    url: str
    capabilities: list[str] = []
    tools_exposed: list[str] = []
    dependencies: list[str] = []
    status: str = "healthy"
    metadata: dict = {}


class HeartbeatRequest(BaseModel):
    load: float = 0.0
    state: str = "healthy"


class RouteRequest(BaseModel):
    task_description: str
    required_capabilities: list[str] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, store, router, cleanup_task

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    store = RegistryStore(redis_client)
    router = CapabilityRouter(store)

    async def cleanup_loop():
        while True:
            try:
                if store:
                    await store.cleanup_stale(timeout_seconds=90)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("cleanup_error")
            await asyncio.sleep(30)

    cleanup_task = asyncio.create_task(cleanup_loop())
    logger.info("registry_server_started")
    yield

    if cleanup_task:
        cleanup_task.cancel()
    if redis_client:
        await redis_client.aclose()
    logger.info("registry_server_stopped")


app = FastAPI(title="S-AI Agent Registry", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/register")
async def register(req: RegisterRequest):
    reg = AgentRegistration(
        name=req.name,
        url=req.url,
        capabilities=req.capabilities,
        tools_exposed=req.tools_exposed,
        dependencies=req.dependencies,
        status=req.status,
        metadata=req.metadata,
    )
    await store.register(reg)
    return {"status": "ok", "name": req.name}


@app.delete("/register/{name}")
async def deregister(name: str):
    removed = await store.deregister(name)
    return {"status": "ok" if removed else "not_found"}


@app.get("/agents")
async def list_agents():
    agents = await store.list_all()
    return {"agents": [a.model_dump() for a in agents]}


@app.get("/agents/{name}")
async def get_agent(name: str):
    agent = await store.get(name)
    if agent is None:
        return {"error": "not_found"}, 404
    return agent.model_dump()


@app.put("/agents/{name}/heartbeat")
async def heartbeat(name: str, req: HeartbeatRequest):
    await store.update_heartbeat(name, load=req.load, state=req.state)
    return {"status": "ok"}


@app.get("/find")
async def find(capability: str | None = None, tool: str | None = None):
    if capability:
        results = await store.find_by_capability(capability)
    elif tool:
        results = await store.find_by_tool(tool)
    else:
        return {"error": "provide capability or tool parameter"}
    return {"agents": [a.model_dump() for a in results]}


@app.post("/route")
async def route_task(req: RouteRequest):
    if req.required_capabilities:
        agent = await router.find_best_agent(req.required_capabilities)
        if agent:
            return {"agent": agent.model_dump()}
    agents = await router.find_agents_for_task(req.task_description)
    return {"agents": [a.model_dump() for a in agents]}


@app.get("/health")
async def health():
    agents = await store.list_all()
    return {
        "status": "healthy",
        "registered_agents": len(agents),
        "healthy_agents": sum(1 for a in agents if a.status == "healthy"),
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=9000)


if __name__ == "__main__":
    main()
