# WEB MODULE KNOWLEDGE BASE

## OVERVIEW
FastAPI backend orchestrator + Vue 3 frontend. Coordinates all MCP servers and provides GLM-4 LLM chat interface for spatial analysis.

## STRUCTURE
```
web/
├── server.py             # MAIN: FastAPI app, MCP coordinator, chat API
├── app/                  # Core application logic
│   ├── config.py         # MCP server endpoints, GLM config, logging setup
│   ├── llm.py            # ZhipuAI GLM-4 API client (async)
│   ├── mcp_client.py     # MCP SSE client for tool execution
│   ├── router.py         # FastAPI route definitions
│   ├── api.py            # Chat, SSE, tool execution endpoints
│   ├── store.py          # Session/conversation state management
│   ├── validators.py     # Request/response validation
│   ├── streaming.py      # SSE streaming for LLM responses
│   └── tools/            # Built-in tools (non-MCP)
├── frontend/             # Vue 3 + TypeScript + Vite
│   └── src/
│       ├── main.ts       # Frontend entry
│       ├── router/       # Vue Router config
│       ├── stores/       # Pinia stores (map, chat, three)
│       ├── composables/  # useServices, useSSE, useToolRenderer
│       └── types/        # TypeScript definitions
├── segment/              # Image segmentation module
├── reconstruct/          # 3D model reconstruction (TripoSR)
├── multi_agent/          # Multi-agent orchestration
├── flood_sim/            # 2D hydrodynamic simulation
├── drone/                # Drone mission planning
├── water_monitor/        # Sentinel-2 satellite water body monitoring
└── static/               # Static assets (Three.js, Leaflet)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| MCP coordination | `web/server.py` | Orchestrates 7 MCP servers, tool routing |
| LLM chat API | `web/app/api.py` | `/chat` endpoint, ReAct reasoning |
| MCP client | `web/app/mcp_client.py` | SSE transport to MCP servers |
| Frontend state | `web/frontend/src/stores/` | Pinia stores for map/chat/three |
| Tool execution | `web/app/streaming.py` | SSE streaming for LLM/tool results |

## CONVENTIONS
- All Python modules use `from __future__ import annotations`
- Async/await throughout (FastAPI routes, MCP calls, LLM API)
- Structlog logging with `[MODULE] >>>` request format
- FastAPI routes in `web/app/router.py`, handlers in `web/app/api.py`
- Vue 3 Composition API with `<script setup>`, Pinia for state
- MCP tool routing via `TOOL_TO_SERVER` dict in `web/app/config.py`

## UNIQUE STYLES
- **MCP-Orchestrator Pattern**: Central web server routes tool calls to 7 specialized MCP servers via SSE
- **ReAct LLM Loop**: MAX_REACT_STEPS=8, tool calls executed via MCP, reasoning accumulated
- **Circuit Breaker**: `_circuit_breaker` dict for MCP server failure handling
- **Tool Cache**: `_tool_cache` OrderedDict with TTL=300s for MCP tool responses
- **Frontend-Backend SSE**: Real-time streaming of LLM thoughts and tool results

## ANTI-PATTERNS
- **NEVER** use synchronous LLM API calls (always `async with httpx.AsyncClient`)
- **NEVER** directly import MCP server code - always use SSE client