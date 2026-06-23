# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-22
**Commit:** 5b69c1ae4fed0da5f514c719b2314b4e0d628dc1
**Branch:** master

## OVERVIEW
S-AI (水利空间智能体平台) - Spatial AI platform for water resources engineering. Combines LLM reasoning, MCP microservices, and spatial visualization for natural language-driven hydrology/gis analysis.

## STRUCTURE
```
S-AI/
├── web/                   # FastAPI backend + Vue 3 frontend
│   ├── app/              # Core FastAPI application (LLM coordination, MCP client)
│   ├── frontend/         # Vue 3 + TypeScript + Vite + Pinia
│   ├── segment/          # Image segmentation module
│   ├── reconstruct/      # 3D model reconstruction (TripoSR)
│   ├── multi_agent/      # Multi-agent orchestration
│   ├── flood_sim/        # 2D hydrodynamic simulation
│   ├── drone/            # Drone mission planning
│   └── water_monitor/    # Satellite water body monitoring
├── servers/              # MCP microservices (7 specialized servers)
│   ├── mcp-gis/          # Spatial query, buffer, overlay, coordinate transform
│   ├── mcp-data/         # Data import/export, spatial queries
│   ├── mcp-knowledge/    # Knowledge base search (ChromaDB)
│   ├── mcp-map/          # Map rendering, choropleth, timeseries
│   ├── mcp-hydro/        # Hydrological design storm, runoff, SWMM
│   ├── mcp-flood/        # Flood inundation, assessment, risk zones
│   └── mcp-raster/       # DEM analysis, watershed, flow accumulation
├── agents/               # Agent system (Dockerfile)
├── registry/             # Agent registry (Dockerfile)
├── knowledge/            # Vector database storage (ChromaDB)
├── data/                 # Geospatial data storage
├── docs/                 # Documentation
└── tests/                # Pytest tests (minimal)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Start all services | `start_all.py` | Launches 7 MCP servers + web server |
| Main backend | `web/server.py` | FastAPI orchestrator, GLM-4 chat interface |
| Frontend entry | `web/frontend/src/main.ts` | Vue 3 app, Pinia, router |
| MCP protocol | `servers/mcp-*/server.py` | Each microservice exports TOOLS via MCP |
| LLM integration | `web/app/llm.py` | ZhipuAI GLM-4 API client |
| Spatial viz | `web/static/`, `web/frontend/src/stores/` | Three.js, Leaflet integration |

## CONVENTIONS

**Python:**
- Line length: 100 chars (Ruff)
- Type checking: MyPy strict mode enabled
- Imports: `from __future__ import annotations` in all modules
- Async: Async/await throughout (FastAPI, MCP servers, LLM calls)
- Logging: `structlog` with timestamps and levels

**Frontend:**
- Vue 3 Composition API with `<script setup>`
- TypeScript strict mode
- Pinia for state management
- Tailwind CSS for styling
- Three.js + Leaflet for spatial visualization

**Testing:**
- pytest with asyncio_mode=auto
- testpaths=["tests"]
- Minimal test infrastructure (currently empty tests/)

## ANTI-PATTERNS (THIS PROJECT)
- **NEVER** suppress type errors with `# type: ignore`
- **NEVER** use synchronous LLM calls (always async)
- Minimal explicit anti-patterns documented

## UNIQUE STYLES

**MCP Architecture:**
- 7 specialized MCP servers (gis, data, knowledge, map, hydro, flood, raster)
- Each server has `server.py` with TOOLS list exported via MCP protocol
- Main web server (`web/server.py`) coordinates all MCP servers via SSE transport

**LLM-Driven:**
- ZhipuAI GLM-4 API for chat and tool calling
- ReAct-style reasoning with MAX_REACT_STEPS=8
- Tool selection via MCP server routing (TOOL_TO_SERVER mapping)
- Structured logging for all LLM interactions

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
python run_gis.py        # MCP GIS server (port 5011)
python run_data.py       # MCP Data server (port 5002)
python run_knowledge.py  # MCP Knowledge server (port 5003)
python run_map.py        # MCP Map server (port 5004)
python run_hydro.py      # MCP Hydro server (port 5015)
python run_flood.py      # MCP Flood server (port 5006)
python run_raster.py     # MCP Raster server (port 5007)

# Frontend development
cd web/frontend
npm run dev              # Vite dev server (port 5173)
npm run build            # TypeScript check + Vite build
npm run preview          # Preview production build

# Docker
docker-compose up        # Start PostGIS, Redis, ChromaDB, MCP servers
```

## NOTES
- MCP servers require specific port assignments (see web/app/config.py)
- ZHIPUAI_API_KEY must be set in .env for LLM functionality
- Frontend dev server runs on 5173, backend on 3000
- No GitHub workflows - use run_*.py scripts for local development
- Project is monorepo-style: web/ and servers/ are co-dependent but modular