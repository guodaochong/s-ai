# MCP SERVERS KNOWLEDGE BASE

## OVERVIEW
7 specialized MCP (Model Context Protocol) microservices providing geospatial, hydrological, and data analysis tools for LLM orchestration.

## STRUCTURE
```
servers/
├── mcp-gis/              # Spatial analysis tools
│   ├── sai_mcp_gis/
│   │   ├── server.py     # MCP server entry
│   │   └── tools/
│   │       ├── spatial_query.py    # Geometry relationships
│   │       ├── vector_io.py        # Import/export GeoJSON
│   │       ├── buffer.py           # Buffer zones
│   │       ├── overlay.py          # Intersection/union/diff
│   │       ├── coordinate_transform.py  # CRS transformation
│   │       └── geometry_properties.py   # Area, length, centroid
│   └── Dockerfile
├── mcp-data/             # Data management tools
│   ├── sai_mcp_data/
│   │   ├── server.py
│   │   └── tools/        # Import data, query_spatial, validate_data
│   └── Dockerfile
├── mcp-knowledge/        # Knowledge base tools
│   ├── sai_mcp_knowledge/
│   │   ├── server.py
│   │   └── tools/        # get_parameter, search, get_standard
│   └── Dockerfile
├── mcp-map/              # Map rendering tools
│   ├── sai_mcp_map/
│   │   ├── server.py
│   │   └── tools/        # render_map, create_choropleth, plot_timeseries
│   └── Dockerfile
├── mcp-hydro/            # Hydrological tools
│   ├── sai_mcp_hydro/
│   │   ├── server.py
│   │   └── tools/        # design_storm, runoff_compute, swmm_create_model
│   └── Dockerfile
├── mcp-flood/            # Flood analysis tools
│   ├── sai_mcp_flood/
│   │   ├── server.py
│   │   └── tools/        # flood_inundation_map, flood_assessment, hydrodynamic_2d_sim
│   └── Dockerfile
└── mcp-raster/           # Terrain/D raster tools
    ├── sai_mcp_raster/
    │   ├── server.py
    │   └── tools/        # dem_analyze, watershed_delineate, flow_accumulation
    └── Dockerfile
```

## WHERE TO LOOK
| Server | Port | Purpose | Key Tools |
|--------|------|---------|-----------|
| mcp-gis | 5011 | Spatial query/overlay | spatial_query, buffer, overlay |
| mcp-data | 5002 | Data import/validate | import_data, query_spatial, validate_data |
| mcp-knowledge | 5003 | Parameter/standard lookup | get_parameter, search, get_standard |
| mcp-map | 5004 | Map visualization | render_map, create_choropleth, plot_timeseries |
| mcp-hydro | 5015 | Hydrology modeling | design_storm, runoff_compute, swmm_create_model |
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

## UNIQUE STYLES
- **SSE Transport**: MCP servers communicate via `SseServerTransport` (not stdio)
- **PostGIS Integration**: mcp-gis and mcp-data use asyncpg for PostGIS database
- **ChromaDB Integration**: mcp-knowledge stores vector embeddings for semantic search
- **Tool Schema Validation**: MCP `Tool.inputSchema` follows JSON Schema for parameter validation
- **Port Standardization**: Each server has assigned port (5011, 5002, 5003, 5004, 5015, 5006, 5007)

## ANTI-PATTERNS
- **NEVER** modify MCP protocol - tools must conform to `mcp.types.Tool` schema
- **NEVER** block in tool handlers - all tools must be async