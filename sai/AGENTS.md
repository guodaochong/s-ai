# SAI DISTRIBUTED AGENT SYSTEM

## OVERVIEW
Redis-backed multi-agent framework. Each agent is simultaneously an MCP server + FastAPI app + LLM reasoner. Agents communicate via EventBus (pub/sub), share state via Blackboard, and self-register with the Registry server.

## STRUCTURE
```
sai/
├── config.py              # pydantic-settings: DB, Redis, ChromaDB, MCP URLs, registry
├── agents/
│   ├── base/
│   │   ├── agent.py       # SpatialAgent ABC — MCP server + FastAPI + lifecycle
│   │   ├── config.py      # AgentConfig dataclass (name, capabilities, max_concurrent)
│   │   └── lifecycle.py   # LifecycleManager: state machine (init→idle→busy→draining)
│   ├── flood/             # FloodAgent — flood simulation + assessment
│   ├── gis/               # GisAgent — spatial query + overlay
│   ├── hydro/             # HydroAgent — hydrological modeling
│   ├── knowledge/         # KnowledgeAgent — parameter lookup + semantic search
│   └── router/            # RouterAgent — task decomposition + agent routing
├── events/
│   ├── bus.py             # EventBus: Redis pub/sub with type/agent filtering
│   ├── blackboard.py      # Blackboard: shared key-value state store (Redis)
│   ├── store.py           # EventStore: append-only event log (Redis lists)
│   └── schemas.py         # AgentEvent, EventType enums
├── llm/
│   ├── client.py          # GLMClient: tenacity retry, typed messages, tool calling
│   └── types.py           # Message, LLMResponse, ToolDefinition, ToolCall, ToolResult
└── registry/
    ├── server.py          # FastAPI registry (port 9000): register, heartbeat, route, discover
    ├── store.py           # RegistryStore: Redis-backed agent registration + cleanup
    └── router.py          # CapabilityRouter: match task → best agent by capabilities
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Agent base class | `agents/base/agent.py` `SpatialAgent` | ABC: MCP server + FastAPI + EventBus |
| Agent lifecycle | `agents/base/lifecycle.py` | State machine: INITIALIZING→IDLE→BUSY→DRAINING→STOPPED |
| Start registry | `registry/server.py` | `python -m sai.registry.server` (port 9000) |
| Register agent | POST `/register` | name, url, capabilities, tools_exposed |
| Agent heartbeat | POST `/heartbeat/{name}` | load, state — stale after 90s |
| Route task | POST `/route` | Returns best agent by capability matching |
| LLM calls | `llm/client.py` `GLMClient.chat()` | glm-5.1, tenacity retry (3 attempts, exp backoff) |
| Inter-agent events | `events/bus.py` `EventBus` | Redis pub/sub: `sai:bus:type:*`, `sai:bus:agent:*` |
| Shared state | `events/blackboard.py` | Redis key-value with TTL |

## CONVENTIONS
- `from __future__ import annotations` in all modules
- `pydantic-settings` BaseSettings for config (`config.py`)
- Redis async client (`redis.asyncio`) for all data layer operations
- All agent methods async (start, stop, handle_tool_call, register_tools)
- structlog with `event_*` named fields
- FastAPI + CORS middleware on every agent and registry

## UNIQUE STYLES
- **Triple Identity**: Each `SpatialAgent` is simultaneously an MCP server (tool provider), FastAPI app (HTTP endpoint), and LLM reasoner (GLMClient)
- **EventBus Pub/Sub**: 3-channel routing — `sai:bus:all` (broadcast), `sai:bus:type:{type}` (by event type), `sai:bus:agent:{name}` (by agent name)
- **Blackboard Pattern**: Shared Redis key-value store for collaborative problem solving — agents read/write partial results
- **Capability Routing**: Registry matches task requirements to agent `capabilities` list, selects by load + health
- **Auto-Cleanup**: Stale agents (no heartbeat in 90s) automatically deregistered by registry background task

## ANTI-PATTERNS
- **NEVER** call agents directly via HTTP — use EventBus for async, Blackboard for state
- **NEVER** block on Redis operations — all async
- **NEVER** create agents without registering with the registry first
