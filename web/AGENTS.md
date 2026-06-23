# WEB MODULE KNOWLEDGE BASE

## OVERVIEW
FastAPI backend orchestrator + Vue 3 frontend. Coordinates all MCP servers, provides GLM-4 LLM chat interface with hybrid tool routing and spatial analysis.

## STRUCTURE
```
web/
├── server.py              # MAIN: FastAPI app, routes, chat_stream, _handle_internal_tool (895 lines)
├── app/                   # Refactored modules — see app/AGENTS.md for details
│   ├── config.py          # GLM_TOOLS, ROUTING_RULES, REACT_SYSTEM_PROMPT, constants
│   ├── router.py          # Hybrid routing: regex → compute override → LLM fallback
│   ├── services.py        # 8 domain functions (extract_buildings, simulate_flood_3d, ...)
│   ├── knowledge.py       # SpatialKG, geocode_city, weather, precipitation, satellite APIs
│   ├── llm.py             # ZhipuAI GLM-4 async client, tool_choice="auto"
│   ├── utils.py           # compress_result, SSE helpers, trim_context
│   ├── store.py           # MemoryStore (episodic/semantic/procedural memory)
│   ├── validators.py      # validate_result, validate_physics, debate_validate
│   ├── multimodal.py      # analyze_image (GLM-4V vision model)
│   ├── auth.py            # JWT authentication middleware
│   ├── mcp_client.py      # MCP SSE client with caching + circuit breaker
│   ├── tracing.py         # TraceSpan, evolution tracking
│   └── tools/             # Subprocess sandbox for LLM-generated code
│       ├── sandbox.py     # exec_in_sandbox via subprocess with timeout
│       └── _sandbox_runner.py  # In-process code runner for sandbox subprocess
├── frontend/              # Vue 3 + TypeScript + Vite + Pinia
│   └── src/
│       ├── main.ts        # Frontend entry
│       ├── router/        # Vue Router config
│       ├── stores/        # Pinia stores (map, chat, three)
│       ├── composables/   # useSSE, useToolRenderer, useServices
│       ├── components/    # 7 UI components
│       ├── views/         # Page views
│       └── types/         # TypeScript definitions
├── segment/               # SAM-based building segmentation (satellite imagery)
├── reconstruct/           # TripoSR 3D model reconstruction from images
├── multi_agent/           # Multi-agent collaborative debate (3 experts × 2 rounds)
├── flood_sim/             # 2D hydrodynamic shallow-water simulation
├── drone/                 # Drone mission planning (waypoint generation)
├── water_monitor/         # Sentinel-2 satellite water body change detection
└── static/                # Static assets (Three.js, Leaflet, fonts)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| API routes | `server.py` | 24 FastAPI routes defined inline |
| Chat streaming | `server.py` `chat_stream()` | SSE ReAct loop, MAX_REACT_STEPS=8 |
| Tool dispatch | `server.py` `_handle_internal_tool()` | Routes to services.py functions |
| Tool generation | `server.py` `_generate_tool()` | LLM-generated Python via sandbox |
| Hybrid routing | `app/router.py` + `app/config.py` | ROUTING_RULES regex → COMPUTE_OVERRIDE → LLM fallback |
| MCP coordination | `server.py` + `app/mcp_client.py` | TOOL_TO_SERVER dict maps tools to MCP endpoints |
| LLM calls | `app/llm.py` `call_llm()` | GLM-4 with tool_choice="auto" |
| Image analysis | `app/multimodal.py` | GLM-4V via MODEL_VISION |
| Knowledge graph | `app/knowledge.py` | SpatialKG + ChromaDB vector search |
| Frontend state | `frontend/src/stores/` | Pinia: chatStore, mapStore, threeStore |
| SSE handling | `frontend/src/composables/useSSE.ts` | Event handler registry |

## CONVENTIONS
- `from __future__ import annotations` in all modules
- Async/await throughout (FastAPI routes, MCP calls, LLM API)
- Structlog logging with `[MODULE] >>>` request format
- `TOOL_TO_SERVER` dict in `app/config.py` maps tool names to MCP server endpoints
- Vue 3 `<script setup>`, Pinia stores, Tailwind CSS
- Internal tools dispatched in `server.py`, MCP tools via `mcp_client.py`

## UNIQUE STYLES
- **Hybrid Routing**: ROUTING_RULES (regex fast path) → _COMPUTE_OVERRIDE_EXEMPT (calc override) → _COMPUTE_FAST (arithmetic bypass) → LLM fallback (Flash model selects tool)
- **ReAct LLM Loop**: MAX_REACT_STEPS=8, reasoning accumulated in context, tools executed per-step
- **Internal Tools** (non-MCP): `flood_sim_3d`, `building_extract`, `water_monitor`, `water_change`, `drone_mission`, `auto_tool` — executed directly in server.py via services.py
- **Circuit Breaker**: `_circuit_breaker` dict for MCP server failure handling
- **Tool Cache**: `_tool_cache` OrderedDict with TTL=300s for MCP tool responses
- **compress_result**: Per-tool result compression in utils.py (prevents LLM re-calling same tool)
- **Sandbox Execution**: LLM-generated code runs in subprocess with timeout + resource limits (`app/tools/sandbox.py`)

## ANTI-PATTERNS
- **NEVER** use synchronous LLM API calls (always `async with httpx.AsyncClient`)
- **NEVER** directly import MCP server code — always use SSE client (`app/mcp_client.py`)
- `app/api.py` and `app/streaming.py` were DELETED — functionality now in `server.py`
- `app/tools/__init__.py` was EMPTIED — `server.py` has its own `_generate_tool`
