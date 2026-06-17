<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/Vue_3.5-4FC08D?style=for-the-badge&logo=vue.js&logoColor=white">
  <img src="https://img.shields.io/badge/Three.js-r160-black?style=for-the-badge&logo=three.js&logoColor=white">
  <img src="https://img.shields.io/badge/FastAPI-0.104+-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  <img src="https://img.shields.io/badge/GLM-5.1-6366F1?style=for-the-badge">
  <img src="https://img.shields.io/badge/MCP-Protocol-F97316?style=for-the-badge">
  <img src="https://img.shields.io/badge/license-MIT-blue?style=for-the-badge">
</p>

<h1 align="center">
  S-AI · Water Resources Spatial Intelligence Platform
</h1>

<p align="center">
  <em>Natural language as the interface. Spatial computation as the engine. Cognitive AI as the soul.</em><br>
  <strong>S-AI</strong> is a cognitive bridge between human language and the Earth's surface.<br>
  One sentence awakens the intelligence dormant in terrain data — making every raindrop's path visible.
</p>

---

## ◆ Vision · Why S-AI Exists

Traditional spatial information systems have a steep learning curve: users must understand coordinate systems, master tool parameters, and memorize operation workflows. The real expert thinking — "examine the terrain first, then compute runoff, then assess inundation risk" — this chain reasoning ability is locked inside the minds of GIS engineers.

**S-AI shatters this barrier.**

We weave together **GLM LLM's reasoning capability**, **MCP microservice protocol's tool orchestration**, and **Leaflet + Three.js spatial visualization** into an organic whole. This is not a chatbot wearing a map shell — this is an **AI agent that genuinely understands "space"**: it infers from a single sentence what tools you need, what parameters, what sequence, and autonomously completes the full chain from DEM sampling to 3D rendering.

```
"What's the elevation and slope at lat 33.197, lng 104.893?"
  → GLM ReAct reasoning → Raster service DEM sampling → result rendered to chat + map

"Will Tianshui flood if 150mm of rain falls in 24 hours?"
  → flood_sim_3d → SRTM DEM → OSM landuse CN → SCS-CN runoff → Time-area routing
  → Manning 2D shallow water → 1,174 buildings individually assessed → hydrograph + depth heatmap animation

"Plan a drone inspection route for Tianshui flood zones"
  → drone_mission → flood risk hotspots → TSP optimization → 3D flight preview → KML export for DJI

"Monitor water bodies in Longnan"
  → water_monitor → Sentinel-2 satellite download → NDWI extraction → polygons + area stats

"Reconstruct this dam in 3D"
  → reconstruct_3d → upload photo → TripoSR AI inference → Three.js GLB viewer
```

---

## ◆ Quick Demo · Core Commands

Type any of these in the chat panel:

| Command | Capability | Effect |
|---------|-----------|--------|
| `Identify buildings in Tianshui city center` | 🏙️ OSM Building Extraction | Satellite imagery + building footprints + 6-class taxonomy |
| `Show 3-day rainfall forecast for Chifeng` | 🌧️ ERA5-Land Precipitation Grid | Animated heatmap + moving storm center + area-average hydrograph |
| `Monitor water bodies in Tianshui` | 🌊 Sentinel-2 NDWI | Satellite download + water polygons + area statistics |
| `Will Tianshui flood with 150mm/24h rain?` | 🌊 Distributed Hydro + 2D Hydrodynamic | SRTM DEM → SCS-CN → routing → inundation → building assessment |
| `Plan drone inspection route for Tianshui flood` | 🚁 Drone Mission Planning | Flood hotspots → TSP optimization → 3D preview → KML export |

> 💡 All commands support any city name (46 built-in + Nominatim geocoding). No manual coordinates needed.

---

## ◆ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      🖥️ Vue 3 Frontend (Port 5173)                          │
│  ┌──────────┐  ┌────────────────────┐  ┌────────────────────────────────┐  │
│  │ SideBar   │  │    MapPanel        │  │       ChatPanel                │  │
│  │ Agent     │  │  Leaflet Dark Map  │  │  SSE real-time streaming       │  │
│  │ History   │  │  Three.js 3D Terrain│  │  Thinking frames + progress   │  │
│  │           │  │  GeoJSON overlays  │  │  Tool status (⏳→✅ live)      │  │
│  │           │  │  Timeline player   │  │  24+ tool render strategies    │  │
│  └──────────┘  └────────────────────┘  └────────────────────────────────┘  │
│  Build: Vite 8 · TypeScript · TailwindCSS v3 · Pinia                       │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │ HTTP/SSE (Vite Proxy :5173 → :3000)
┌──────────────────────────▼──────────────────────────────────────────────────┐
│                ⚡ FastAPI Orchestration Layer (Port 3000)                     │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    🧠 GLM-5.1 Reasoning Engine                       │   │
│  │  3-Layer Routing → ReAct (8-step) → Debate Validation → ToT        │   │
│  │  Auto-tool Generation + Self-repair + Physics Validation            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              🛡️ Reliability Infrastructure                           │   │
│  │  Circuit Breaker · LRU Cache · Trace Spans · Self-evolution        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │ MCP Protocol (HTTP/JSON)
    ┌───────┬───────┬──────┴──────┬───────┬───────┬───────┐
  GIS    Data   Knowledge    Map   Hydro   Flood   Raster
 :5001  :5002    :5003       :5004  :5005   :5006   :5007
```

---

## ◆ Distributed Hydrology × 2D Hydrodynamic Inundation

The crown jewel of S-AI — from a single sentence to a complete **rainfall → runoff → routing → inundation → building assessment** physics-based pipeline in 13 seconds.

### Full Technical Pipeline

```
Step 1: City Geocoding
  GLM passes location → 46 built-in cities / Nominatim geocoding → bbox (~3km²)

Step 2: SRTM Global DEM Acquisition
  Terrarium SRTM 90m COG (AWS CloudFront, free, no API key)
  → rasterio windowed read → 106×66 elevation grid (51m/px)
  → 3-tier fallback: Terrarium → Open-Meteo elevation → synthetic

Step 3: Watershed Delineation
  D8 flow direction (8-neighbor steepest descent)
  → Topological sort flow accumulation (BFS queue)
  → Stream network extraction (facc > μ+3σ) → confluence node detection

Step 4: Distributed SCS-CN Runoff Generation
  Dual-source CN fusion:
  ├─ OSM land use (428 polygons): residential→85, commercial→92, forest→55, water→98
  │  → matplotlib Path rasterization to DEM grid
  └─ Slope fallback (uncovered areas): <3°→82, 8-15°→72, >25°→58
  CN range: 55-98 (urban areas accurately identified)
  → SCS-CN: excess = (P-Ia)² / (P+0.8S), S=25400/CN-254

Step 5: Time-Area Flow Routing
  Travel time: t = Σ(distance / velocity) along D8 flow path
  velocity = (1/n) · R^(2/3) · S^(1/2)  (Manning's equation)
  → Time-area histogram (30 bins by distance to outlet)
  → Rainfall excess × histogram → outlet discharge Q(t)
  Output: peak discharge 59.5 m³/s @ 2.5h

Step 6: 2D Shallow Water Inundation
  Per timestep (dt=15min, 25 steps):
  a. Distributed rainfall inflow: depth[r,c] += excess × rain_factor × dt
  b. Channel discharge injection: node Q(t) injected to stream cells (30% weight)
  c. Manning 8-neighbor diffusion:
     v = (1/n) · h^(2/3) · S^(1/2), q = v · h · cell / 8
     Conservation: depth[r,c] -= Σout, depth[nr,nc] += Σin
  Output: peak depth 3.12m, 56.9% area flooded

Step 7: Building-Level Impact Assessment
  OSM building footprints → DEM elevation sampling → peak depth sampling
  → Per building: safe / partial / submerged + flood depth + floors flooded
  Output: 1,174 buildings — ✅669 safe / ⚠️505 partial / ❌0 submerged

Step 8: Visualization
  Chat card: discharge hydrograph SVG + watershed parameters
  Map: depth heatmap grid + building polygons + timeline animation
  Stats panel: peak Q, depth, flooded area, CN distribution, stream density
```

### Key Metrics

| Metric | Value | Note |
|--------|-------|------|
| Total pipeline time | **13-18s** | Including DEM download + OSM query + physics simulation |
| DEM resolution | 90m (SRTM) | Global coverage, free |
| CN accuracy | 55-98 (OSM) | Land-use driven, urban-precise |
| Discharge time series | 25 steps | Time-area method + Manning routing |
| 2D inundation | 13 depth frames | Shallow water per-cell diffusion |
| Building assessment | Per-building | 1,174 OSM buildings × peak depth |
| Data sources | All free | SRTM + OSM + Open-Meteo, zero API cost |

---

## ◆ Autonomous Drone Mission Planning

When flood simulation completes, AI automatically identifies risk hotspots and generates optimal drone inspection routes — **from digital twin output to real-world action**.

### Pipeline

```
Flood results → Risk hotspot identification → Waypoint generation
  → TSP path optimization (nearest neighbor + 2-opt) → 3D flight preview → KML export
```

- **AI-selected waypoints**: Clusters 1,174 buildings into 6 inundation zones + 4 deep-water areas = 10 high-risk waypoints
- **Multi-mission profiles**: Flood inspection (80m snake) / Dam inspection (50m linear) / Search & rescue (40m spiral) / Damage assessment (120m grid)
- **Session coupling**: Reuses flood results within 5 minutes (bbox overlap detection) — no redundant simulation
- **DJI export**: One-click KML download, import directly to DJI Pilot for real-world flight execution

---

## ◆ AI Vision & Remote Sensing

### 🏗️ 3D Reconstruction (TripoSR)
Single photo → 3D mesh in <1 second. GLB export + Three.js viewer with orbit/zoom/download.

### 🏙️ Building Extraction (OSM + SAM)
| Source | Accuracy | Speed | Features |
|--------|----------|-------|----------|
| **OSM (primary)** | ~95%+ | ~8s | Precise footprints + type tags + floor count |
| **SAM (fallback)** | ~60% | ~70s | AI segmentation from satellite imagery |

6-class taxonomy: 🏠 Low-rise residential · 🏢 High-rise · 🏬 Commercial · 🏭 Industrial · 🏫 Public · 🔧 Ancillary

### 🌊 Water Body Monitoring (Sentinel-2)
Automatic Sentinel-2 L2A download (10m) → NDWI = (Green - NIR) / (Green + NIR) → polygon extraction. Free via element84 STAC API + AWS S3.

### 🌧️ Precipitation Grid (ERA5-Land 9km)
Hourly precipitation grid animation with 6-level meteorological color scale. Storm center marker moves per timestep with reverse geocoding for place names.

---

## ◆ Reliability Infrastructure

| Module | Implementation |
|--------|---------------|
| Circuit breaker | 3 failures → 120s cooldown |
| LRU cache | 200 entries, 5min TTL |
| Full-chain tracing | TraceSpan (route/LLM/tool/render) |
| Self-evolution | Route accuracy learning |
| Agent memory | SQLite (episodes/facts/procedures) |
| Flood result caching | 5min TTL, bbox overlap detection |

---

## ◆ Capability Matrix · 42+ Tools

### 🤖 AI Vision & Remote Sensing (6 tools)

| Tool | Description |
|------|-------------|
| `reconstruct_3d` | AI 3D reconstruction from single photo (TripoSR) |
| `building_extract` | OSM building footprints + SAM fallback, 6-class taxonomy |
| `water_monitor` | Sentinel-2 NDWI water body extraction, free |
| `precipitation_grid` | ERA5-Land 9km hourly precipitation, animated heatmap |
| `flood_sim_3d` | Distributed hydro + 2D hydrodynamic inundation simulation |
| `drone_mission` | Flood-driven drone route planning + KML export |

### 🗺️ GIS Spatial Analysis (8 tools)
`spatial_query` · `buffer` · `overlay` · `coordinate_transform` · `geometry_properties` · `read/write_vector` · `validate_data` · `import_network`

### 🏔️ Raster Terrain (5 tools)
`dem_analyze` · `flow_accumulation` · `watershed_delineate` · `terrain_profile` · `scatter_interpolate`

### 💧 Hydrology (5 tools)
`design_storm` · `runoff_compute` · `swmm_simulate` · `calibrate_suggest` · `hydrodynamic_2d_sim`

### 🌊 Flood (5 tools)
`flood_inundation_map` · `flood_assessment` · `drainage_assessment` · `flood_warning` · `flood_risk_zones`

### 📚 Knowledge + Data + Map (13+ tools)
`get_parameter` · `explain_concept` · `search` · `get_standard` · `render_map` · `weather_forecast` · `satellite_search` · `spatial_knowledge_query` · `auto_tool`

---

## ◆ Quick Start

```bash
# 1. API Key
export ZHIPUAI_API_KEY=your_key_here

# 2. Python dependencies
pip install fastapi uvicorn httpx rasterio geopandas shapely \
            numpy scipy pyswmm structlog python-dotenv \
            segment-anything torch torchvision pillow opencv-python pyproj

# 3. Start backend (7 MCP + Web Server)
python web/server.py
# → Web:3000  GIS:5001  Data:5002  Knowledge:5003
# → Map:5004  Hydro:5005  Flood:5006  Raster:5007

# 4. Start frontend
cd web/frontend && npm install && npm run dev
# → Vite :5173 (proxies /api/* → :3000)
```

---

## ◆ Project Structure

```
S-AI/
├── web/
│   ├── server.py                    # Backend orchestration (2600+ lines)
│   ├── reconstruct/                 # TripoSR 3D reconstruction
│   ├── segment/                     # SAM + OSM building extraction
│   ├── water_monitor/              # Sentinel-2 NDWI
│   ├── flood_sim/                  # Distributed hydro + 2D hydrodynamic
│   │   ├── engine.py               # DEM + D8 flow + Manning 2D
│   │   └── hydro_chain.py          # Stream network + CN + routing
│   ├── drone/                      # Autonomous drone mission planning
│   └── frontend/                   # Vue 3 + Vite + Three.js
├── servers/                        # 7 MCP microservices
└── .env                            # ZHIPUAI_API_KEY
```

---

## ◆ Design Decisions

**Why MCP microservices?** Each spatial domain has radically different computation paradigms. MCP provides: fault isolation, independent scaling, hot-swappable tools, circuit-breaker protection.

**Why ReAct over Function Calling?** Function calling picks one tool at a time. Water resources analysis is inherently multi-step: examine terrain → compute runoff → assess risk. ReAct loops let the LLM observe each step's result and dynamically adjust strategy.

**Why OSM land use for CN?** Traditional SCS-CN requires land cover + soil maps that cost money. OSM provides free, crowd-sourced land use polygons (residential, commercial, forest, water) that map directly to CN values — accurate enough for rapid assessment, zero data cost.

**Why not full Saint-Venant equations?** Complete 2D shallow water equations require implicit solvers with small timesteps (CFL condition). Our Manning diffusion wave approximation runs 100× faster while capturing the essential physics for flood inundation mapping at 50-90m resolution.

---

## ◆ License

MIT License — free to use, contributions welcome.

---

<p align="center">
  <sub>Built with passion by <strong>LUOBIN-PI Research Lab</strong></sub><br>
  <sub>Making spatial intelligence accessible to everyone</sub>
</p>
