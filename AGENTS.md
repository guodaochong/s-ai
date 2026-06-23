# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-23
**Commit:** 244afdb
**Branch:** master

## OVERVIEW
S-AI (水利空间智能体平台) — Spatial AI platform for water resources engineering. Combines LLM reasoning (GLM-4), MCP microservices (7 servers), and spatial visualization (Three.js/Leaflet) for natural language-driven hydrology/GIS analysis.

## STRUCTURE
```
S-AI/
├── web/                   # FastAPI backend + Vue 3 frontend (main app)
│   ├── server.py          # Entry point: routes, chat_stream, tool gen, _handle_internal_tool (895 lines)
│   ├── app/               # Refactored modules (config, router, services, knowledge, utils, ...)
│   │   ├── config.py      # GLM_TOOLS, ROUTING_RULES, REACT_SYSTEM_PROMPT, MCP endpoints
│   │   ├── router.py      # Hybrid routing: regex rules → compute override → LLM fallback
│   │   ├── services.py    # 8 domain functions (extract_buildings, simulate_flood_3d, ...)
│   │   ├── knowledge.py   # SpatialKG, geocode_city, weather, precipitation, satellite APIs
│   │   ├── llm.py         # ZhipuAI GLM-4 async client with tool_choice="auto"
│   │   ├── utils.py       # compress_result, SSE helpers, trim_context
│   │   ├── store.py       # MemoryStore (episodic/semantic/procedural recall)
│   │   ├── validators.py  # validate_result, validate_physics, debate_validate
│   │   ├── multimodal.py  # analyze_image (GLM-4V vision model)
│   │   ├── auth.py        # JWT authentication middleware
│   │   ├── mcp_client.py  # MCP SSE client with caching + circuit breaker
│   │   ├── tracing.py     # TraceSpan, evolution tracking
│   │   └── tools/         # Subprocess sandbox for generated code execution
│   ├── frontend/          # Vue 3 + TypeScript + Vite + Pinia
│   ├── segment/           # SAM-based building segmentation (satellite imagery)
│   ├── reconstruct/       # TripoSR 3D model reconstruction from images
│   ├── multi_agent/       # Multi-agent collaborative debate (3 experts × 2 rounds)
│   ├── flood_sim/         # 2D hydrodynamic shallow-water simulation
│   ├── drone/             # Drone mission planning (waypoint generation)
│   └── water_monitor/     # Sentinel-2 satellite water body change detection
├── servers/               # 7 MCP microservices (each independent, Docker-ready)
│   ├── mcp-gis/           # Port 5001: spatial query, buffer, overlay, CRS transform
│   ├── mcp-data/          # Port 5002: data import/export, spatial queries
│   ├── mcp-knowledge/     # Port 5003: parameter lookup, semantic search (ChromaDB)
│   ├── mcp-map/           # Port 5004: map rendering, choropleth, timeseries
│   ├── mcp-hydro/         # Port 5005: design storm, runoff, SWMM modeling
│   ├── mcp-flood/         # Port 5006: flood inundation, assessment, risk zones
│   └── mcp-raster/        # Port 5007: DEM analysis, watershed, flow accumulation
├── sai/                   # Distributed agent system (Redis + MCP + FastAPI)
│   ├── agents/            # 5 domain agents (flood, gis, hydro, knowledge, router) + base ABC
│   ├── events/            # EventBus (Redis pub/sub), Blackboard, EventStore
│   ├── llm/               # GLMClient with tenacity retry, typed LLM messages
│   └── registry/          # Agent registry server (capability routing, heartbeat)
├── knowledge/             # ChromaDB vector database storage
├── data/                  # Geospatial data, SQLite DBs, generated tools
├── tests/                 # Pytest tests (conftest.py with asyncio support)
├── docs/                  # Documentation and images
└── paper_html/            # Academic paper HTML rendering (generated)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Start all services | `start_all.py` | Launches 7 MCP servers + web server |
| Main backend | `web/server.py` | FastAPI orchestrator (895 lines, slimmed from 2677) |
| App modules | `web/app/` | 13 Python modules — see `web/app/AGENTS.md` |
| Frontend entry | `web/frontend/src/main.ts` | Vue 3 app, Pinia, router |
| MCP protocol | `servers/mcp-*/server.py` | Each exports TOOLS via MCP — see `servers/AGENTS.md` |
| LLM integration | `web/app/llm.py` | GLM-4 async client, tool_choice="auto" |
| Tool routing | `web/app/router.py` + `web/app/config.py` | Hybrid: regex → compute override → LLM fallback |
| Spatial viz | `web/static/`, `web/frontend/src/stores/` | Three.js (3D flood), Leaflet (2D map) |
| Distributed agents | `sai/` | Agent system with Redis EventBus — see `sai/AGENTS.md` |
| Agent registry | `sai/registry/server.py` | Capability-based agent discovery (port 9000) |

## CONVENTIONS

**Python:**
- Line length: 100 chars (Ruff)
- Type checking: MyPy strict mode enabled
- Imports: `from __future__ import annotations` in all modules
- Async: Async/await throughout (FastAPI, MCP servers, LLM calls)
- Logging: `structlog` with timestamps and levels
- Config: `pydantic-settings` BaseSettings in `sai/config.py`

**Frontend:**
- Vue 3 Composition API with `<script setup>`
- TypeScript strict mode
- Pinia for state management
- Tailwind CSS for styling
- Three.js + Leaflet for spatial visualization

**Testing:**
- pytest with asyncio_mode=auto
- testpaths=["tests"], pythonpath=["web"]
- conftest.py provides asyncio fixture + web path setup

## ANTI-PATTERNS (THIS PROJECT)
- **NEVER** suppress type errors with `# type: ignore`
- **NEVER** use synchronous LLM calls (always async)
- **NEVER** directly import MCP server code — always use SSE client (`web/app/mcp_client.py`)
- **NEVER** modify MCP protocol — tools must conform to `mcp.types.Tool` schema

## UNIQUE STYLES

**Hybrid Tool Routing (post-refactor):**
- `ROUTING_RULES`: regex patterns for deterministic tool selection (fast path)
- `_COMPUTE_OVERRIDE_EXEMPT`: calculation requests override non-protected tools
- `_COMPUTE_FAST`: pure arithmetic bypasses LLM entirely
- LLM fallback: Flash model selects tool when no regex matches

**MCP-Orchestrator Pattern:**
- 7 specialized MCP servers (gis, data, knowledge, map, hydro, flood, raster)
- Each server has `server.py` with TOOLS list exported via MCP protocol
- Main web server coordinates all MCP servers via SSE transport
- `TOOL_TO_SERVER` dict maps tool names to server endpoints

**ReAct LLM Loop:**
- ZhipuAI GLM-4 (Flash/Air/Vision/Code model variants)
- MAX_REACT_STEPS=8, tool calls executed via MCP or internal handlers
- `_handle_internal_tool`: dispatches to services.py functions (flood_sim_3d, building_extract, etc.)

**Internal Tools (non-MCP):**
- `flood_sim_3d`, `building_extract`, `water_monitor`, `water_change`, `drone_mission`
- Executed directly in `web/server.py` via `web/app/services.py`
- `auto_tool`: subprocess sandbox for LLM-generated Python code

**Distributed Agent System (`sai/`):**
- `SpatialAgent` ABC: each agent is simultaneously an MCP server + FastAPI app
- EventBus: Redis pub/sub for inter-agent communication
- Blackboard: shared state store for collaborative problem solving
- Registry: capability-based agent discovery with heartbeat + auto-cleanup

**Multi-Language Stack:**
- Python backend (FastAPI, MCP, geospatial libs)
- TypeScript frontend (Vue 3, Vite)
- Docker Compose for service orchestration

## COMMANDS
```bash
# Start all services (7 MCP servers + web server)
python start_all.py

# Start individual services
python run_web.py        # Frontend + backend (port 3000)
python run_gis.py        # MCP GIS server (port 5001)
python run_data.py       # MCP Data server (port 5002)
python run_knowledge.py  # MCP Knowledge server (port 5003)
python run_map.py        # MCP Map server (port 5004)
python run_hydro.py      # MCP Hydro server (port 5005)
python run_flood.py      # MCP Flood server (port 5006)
python run_raster.py     # MCP Raster server (port 5007)

# Frontend development
cd web/frontend
npm run dev              # Vite dev server (port 5173)
npm run build            # TypeScript check + Vite build
npm run preview          # Preview production build

# Docker
docker-compose up        # Start PostGIS, Redis, ChromaDB, MCP servers

# Tests
pytest                   # Run tests with asyncio support
```

## NOTES
- MCP server ports: 5001-5007 (GIS=5001, Hydro=5005 — NOT 5011/5015)
- `ZHIPUAI_API_KEY` must be set in `.env` for LLM functionality
- Frontend dev server runs on 5173, backend on 3000
- `web/app/api.py` and `web/app/streaming.py` were DELETED during refactoring (functionality now in `server.py`)
- `web/app/tools/__init__.py` was emptied (509 lines dead code removed; `server.py` has its own `_generate_tool`)
- Agent registry runs on port 9000 (`sai/registry/server.py`)
- `paper_html/` contains generated academic paper HTML — not source code
