# WEB/APP MODULE KNOWLEDGE BASE

## OVERVIEW
13 Python modules extracted from server.py refactoring (2677→895 lines). Contains config, routing, domain services, LLM client, knowledge graph, memory store, validators, and sandbox — all imported by `web/server.py`.

## STRUCTURE
```
app/
├── config.py              # Central configuration (209 lines)
├── router.py              # Hybrid tool routing (43 lines)
├── services.py            # 8 domain service functions (356 lines)
├── knowledge.py           # Knowledge graph + external APIs (393 lines)
├── llm.py                 # GLM-4 async client (65 lines)
├── utils.py               # Result compression + SSE helpers (328 lines)
├── store.py               # MemoryStore for episodic/semantic memory (161 lines)
├── validators.py          # Physics + result validation (161 lines)
├── multimodal.py          # GLM-4V image analysis (24 lines)
├── auth.py                # JWT middleware (32 lines)
├── mcp_client.py          # MCP SSE client (87 lines)
├── tracing.py             # Trace spans + evolution (104 lines)
└── tools/
    ├── __init__.py        # Empty (was 509 lines, removed — server.py has own _generate_tool)
    ├── sandbox.py         # Subprocess sandbox with timeout (124 lines)
    └── _sandbox_runner.py # In-process runner for sandbox subprocess (56 lines)
```

## WHERE TO LOOK
| Task | Location | Export | Notes |
|------|----------|--------|-------|
| Tool definitions | `config.py` | `GLM_TOOLS` | 12 function-calling schemas for GLM-4 |
| Routing rules | `config.py` | `ROUTING_RULES` | Regex patterns → tool name mapping |
| System prompt | `config.py` | `REACT_SYSTEM_PROMPT` | Tool selection reference for LLM |
| MCP endpoints | `config.py` | `MCP_SERVERS` | 7 server URLs (5001-5007) |
| Tool→Server map | `config.py` | `TOOL_TO_SERVER` | Internal tools + MCP tools → endpoint |
| Protected tools | `config.py` | `CRITICAL_TOOLS` | Tools that can't be overridden by compute |
| Route a message | `router.py` | `route_message()` | Hybrid: regex→compute→LLM fallback |
| Flood simulation | `services.py` | `simulate_flood_3d()` | 3D flood depth grid + buildings |
| Building extraction | `services.py` | `extract_buildings()` | SAM segmentation + OSM fallback |
| Water monitoring | `services.py` | `water_change()` | Sentinel-2 MNDWI diff |
| Drone mission | `services.py` | `drone_mission()` | Waypoint generation |
| Weather | `knowledge.py` | `fetch_weather()` | CMA weather API |
| Precipitation | `knowledge.py` | `fetch_precipitation_grid()` | Gridded rainfall (observed/forecast) |
| Geocoding | `knowledge.py` | `geocode_city()` | City name → bbox |
| Knowledge graph | `knowledge.py` | `SpatialKG` | SQLite-backed entity/relation graph |
| Memory recall | `store.py` | `MemoryStore` | Episodic, semantic, procedural recall |
| LLM call | `llm.py` | `call_llm()` | GLM-4 with tool_choice="auto" |
| Image analysis | `multimodal.py` | `analyze_image()` | GLM-4V via MODEL_VISION |
| Result compression | `utils.py` | `compress_result()` | Per-tool result summarizer |
| SSE helpers | `utils.py` | `sse_*()` | Server-Sent Events formatting |
| Code sandbox | `tools/sandbox.py` | `exec_in_sandbox()` | Subprocess with timeout + resource limits |
| Physics check | `validators.py` | `validate_physics()` | Sanity check on simulation results |
| Debate validation | `validators.py` | `debate_validate()` | Multi-agent cross-validation |

## CONVENTIONS
- `from __future__ import annotations` in every module
- All functions async where I/O involved (LLM, HTTP, file ops)
- structlog with module-level `logger = structlog.get_logger(__name__)`
- Global state vars prefixed with `_` (e.g., `_last_flood_result`, `_precip_cache`)
- `TOOL_TO_SERVER` dict registers both MCP tools and internal tools (non-MCP → `"internal"`)
- `compress_result` switches on tool name to apply per-tool summarization logic

## UNIQUE STYLES
- **Hybrid Routing Pipeline**: `ROUTING_RULES` (regex match) → `_COMPUTE_OVERRIDE_EXEMPT` (calc requests bypass non-protected) → `_COMPUTE_FAST` (pure arithmetic, no LLM) → LLM fallback (Flash model picks tool)
- **Internal Tool Registration**: Non-MCP tools (`flood_sim_3d`, `building_extract`, etc.) registered in `TOOL_TO_SERVER` with value `"internal"` — dispatched by `server.py._handle_internal_tool()` to `services.py` functions
- **Per-Tool Compression**: `compress_result()` in utils.py reduces large tool outputs (e.g., 2.5MB flood grids) before feeding back to LLM — prevents context overflow and redundant tool calls
- **Sandbox Execution**: LLM-generated Python code runs via `exec_in_sandbox()` — separate subprocess with timeout, resource limits, and restricted imports
- **GLM_TOOLS Schema**: Each tool definition is a dict with `type: "function"` and `function: {name, description, parameters}` — compatible with OpenAI function calling format

## ANTI-PATTERNS
- **NEVER** add new tool to `GLM_TOOLS` without also registering in `TOOL_TO_SERVER`
- **NEVER** use synchronous HTTP calls — always `httpx.AsyncClient`
- **NEVER** suppress type errors — fix the type annotation instead
- `app/api.py` and `app/streaming.py` DELETED — all routes/streaming now in `server.py`
- `app/tools/__init__.py` EMPTIED — `server.py` has its own `_generate_tool` with different prompt/model
