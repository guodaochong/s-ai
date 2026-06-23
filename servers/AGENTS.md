# MCP SERVERS KNOWLEDGE BASE

## OVERVIEW
7 specialized MCP (Model Context Protocol) microservices providing geospatial, hydrological, and data analysis tools. Each runs independently as a FastAPI + MCP server with Docker support.

## STRUCTURE
```
servers/
├── mcp-gis/              # Port 5001: Spatial analysis
│   ├── sai_mcp_gis/
│   │   ├── server.py     # MCP server entry
│   │   └── tools/
│   │       ├── spatial_query.py          # Geometry relationships
│   │       ├── vector_io.py              # Import/export GeoJSON
│   │       ├── buffer.py                 # Buffer zones
│   │       ├── overlay.py               # Intersection/union/diff
│   │       ├── coordinate_transform.py   # CRS transformation
│   │       └── geometry_properties.py    # Area, length, centroid
│   └── Dockerfile
├── mcp-data/             # Port 5002: Data management
│   ├── sai_mcp_data/
│   │   ├── server.py
│   │   └── tools/        # import_data, query_spatial, validate_data
│   └── Dockerfile
├── mcp-knowledge/        # Port 5003: Knowledge base
│   ├── sai_mcp_knowledge/
│   │   ├── server.py
│   │   └── tools/        # get_parameter, search, get_standard
│   └── Dockerfile
├── mcp-map/              # Port 5004: Map rendering
│   ├── sai_mcp_map/
│   │   ├── server.py
│   │   └── tools/        # render_map, create_choropleth, plot_timeseries
│   └── Dockerfile
├── mcp-hydro/            # Port 5005: Hydrological modeling
│   ├── sai_mcp_hydro/
│   │   ├── server.py
│   │   └── tools/        # design_storm, runoff_compute, swmm_create_model
│   └── Dockerfile
├── mcp-flood/            # Port 5006: Flood simulation
│   ├── sai_mcp_flood/
│   │   ├── server.py
│   │   └── tools/        # flood_inundation_map, flood_assessment, hydrodynamic_2d_sim
│   └── Dockerfile
└── mcp-raster/           # Port 5007: Terrain/D raster analysis
    ├── sai_mcp_raster/
    │   ├── server.py
    │   └── tools/        # dem_analyze, watershed_delineate, flow_accumulation
    └── Dockerfile
```

## WHERE TO LOOK
| Server | Port | Purpose | Key Tools |
|--------|------|---------|-----------|
| mcp-gis | 5001 | Spatial query/overlay | spatial_query, buffer, overlay, coordinate_transform |
| mcp-data | 5002 | Data import/validate | import_data, query_spatial, validate_data |
| mcp-knowledge | 5003 | Parameter/standard lookup | get_parameter, search, get_standard |
| mcp-map | 5004 | Map visualization | render_map, create_choropleth, plot_timeseries |
| mcp-hydro | 5005 | Hydrology modeling | design_storm, runoff_compute, swmm_create_model |
| mcp-flood | 5006 | Flood simulation | flood_inundation_map, flood_assessment, hydrodynamic_2d_sim |
| mcp-raster | 5007 | Terrain analysis | dem_analyze, watershed_delineate, flow_accumulation |

## CONVENTIONS
- Each MCP server: `sai_mcp_*/server.py` + `sai_mcp_*/tools/`
- Standard MCP server structure:
  ```python
  from mcp.server import Server
  from mcp.server.sse import SseServerTransport
  from mcp.types import Tool

  TOOLS: list[Tool] = [
      Tool(name="...", description="...", inputSchema={...}),
  ]

  app = Server("mcp-xxx")
  @app.call_tool()
  async def handle_call_tool(...) -> ...
  ```
- All tools use GeoJSON geometry format for spatial operations
- Structlog logging with `[MODULE]` prefixes
- Dockerfile for each server (uvicorn + FastAPI + MCP)
- No inter-server imports — each server is fully independent

## UNIQUE STYLES
- **SSE Transport**: MCP servers communicate via `SseServerTransport` (not stdio)
- **PostGIS Integration**: mcp-gis and mcp-data use asyncpg for PostGIS database
- **ChromaDB Integration**: mcp-knowledge stores vector embeddings for semantic search
- **Tool Schema Validation**: MCP `Tool.inputSchema` follows JSON Schema for parameter validation
- **Port Standardization**: 5001-5007 (sequential, GIS=5001 through raster=5007)

## ANTI-PATTERNS
- **NEVER** modify MCP protocol — tools must conform to `mcp.types.Tool` schema
- **NEVER** block in tool handlers — all tools must be async
- **NEVER** import between MCP servers — they are independent services
