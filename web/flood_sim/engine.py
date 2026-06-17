import httpx
import numpy as np
import math
import io
import logging
from PIL import Image

logger = logging.getLogger(__name__)

ELEVATION_API = "https://api.open-meteo.com/v1/elevation"
TERRARIUM_URL = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"


def _latlon_to_tile(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


def _tile_to_latlon(x, y, z):
    n = 2 ** z
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def _decode_terrarium(img):
    r, g, b = img[:,:,0].astype(np.float64), img[:,:,1].astype(np.float64), img[:,:,2].astype(np.float64)
    return r * 256 + g + b / 256 - 32768


async def fetch_elevation_grid(bbox: list[float], grid_n: int = 50) -> dict:
    west, south, east, north = bbox
    for fn in (_fetch_terrarium, _fetch_openmeteo):
        try:
            return await fn(bbox, grid_n)
        except Exception as e:
            logger.warning(f"[flood_sim] {fn.__name__} failed: {e}")
    logger.warning("[flood_sim] All elevation APIs failed, synthetic terrain")
    return _synthetic_terrain(bbox, grid_n)


async def _fetch_terrarium(bbox, grid_n):
    west, south, east, north = bbox
    z = 12
    cx_lon = (west + east) / 2
    cy_lat = (south + north) / 2
    tx, ty = _latlon_to_tile(cy_lat, cx_lon, z)
    url = TERRARIUM_URL.format(z=z, x=tx, y=ty)

    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(url)
        r.raise_for_status()
        img = np.array(Image.open(io.BytesIO(r.content)))

    elev_full = _decode_terrarium(img)
    lat_n, lon_w = _tile_to_latlon(tx, ty, z)
    lat_s, lon_e = _tile_to_latlon(tx + 1, ty + 1, z)

    col0 = max(0, int((west - lon_w) / (lon_e - lon_w) * img.shape[1]))
    col1 = min(img.shape[1], int((east - lon_w) / (lon_e - lon_w) * img.shape[1]))
    row0 = max(0, int((north - lat_n) / (lat_s - lat_n) * img.shape[0]))
    row1 = min(img.shape[0], int((south - lat_n) / (lat_s - lat_n) * img.shape[0]))

    crop = elev_full[row0:row1, col0:col1].copy()
    crop = np.where(crop < -1000, np.nan, crop)
    if crop.shape[0] < 5 or crop.shape[1] < 5:
        raise ValueError("Crop too small")

    lats = np.linspace(north, south, crop.shape[0])
    lons = np.linspace(west, east, crop.shape[1])
    grid = np.nan_to_num(crop, nan=np.nanmean(crop))

    return {
        "grid": grid.tolist(), "grid_n": grid.shape[0], "grid_m": grid.shape[1],
        "lats": lats.tolist(), "lons": lons.tolist(),
        "min_elev": float(np.nanmin(crop)), "max_elev": float(np.nanmax(crop)),
        "mean_elev": float(np.nanmean(crop)),
        "resolution_m": abs(lons[1]-lons[0]) * 111320 * math.cos(math.radians(cy_lat)),
        "bbox": bbox, "source": "Terrarium SRTM 90m",
    }


async def _fetch_openmeteo(bbox, grid_n):
    west, south, east, north = bbox
    lats_arr = np.linspace(south, north, grid_n)
    lons_arr = np.linspace(west, east, grid_n)
    points = [(round(float(la),5), round(float(lo),5)) for la in lats_arr for lo in lons_arr]
    elevations = []
    async with httpx.AsyncClient(timeout=30) as c:
        for i in range(0, len(points), 100):
            batch = points[i:i+100]
            lat_str = ",".join(str(p[0]) for p in batch)
            lon_str = ",".join(str(p[1]) for p in batch)
            resp = await c.get(ELEVATION_API, params={"latitude": lat_str, "longitude": lon_str})
            resp.raise_for_status()
            for r in resp.json().get("results", []):
                elevations.append(float(r.get("elevation", 0)))
    grid = np.array(elevations[:grid_n*grid_n]).reshape(grid_n, grid_n)
    return {
        "grid": grid.tolist(), "grid_n": grid_n, "grid_m": grid_n,
        "lats": lats_arr.tolist(), "lons": lons_arr.tolist(),
        "min_elev": float(grid.min()), "max_elev": float(grid.max()),
        "mean_elev": float(grid.mean()),
        "resolution_m": abs(lons_arr[1]-lons_arr[0]) * 111320 * math.cos(math.radians((south+north)/2)),
        "bbox": bbox, "source": "Open-Meteo Elevation",
    }


def _synthetic_terrain(bbox, grid_n):
    west, south, east, north = bbox
    lats = np.linspace(north, south, grid_n)
    lons = np.linspace(west, east, grid_n)
    Lon, Lat = np.meshgrid(lons, lats)
    cx, cy = (west+east)/2, (south+north)/2
    base = 1000 + (Lon - cx) * 5000 + (Lat - cy) * 3000
    np.random.seed(42)
    noise = np.random.normal(0, 8, (grid_n, grid_n))
    import scipy.ndimage as ndi
    noise = ndi.gaussian_filter(noise, sigma=2)
    grid = base + noise
    return {
        "grid": grid.tolist(), "grid_n": grid_n, "grid_m": grid_n,
        "lats": lats.tolist(), "lons": lons.tolist(),
        "min_elev": float(grid.min()), "max_elev": float(grid.max()),
        "mean_elev": float(grid.mean()),
        "resolution_m": abs(lons[1]-lons[0]) * 111320 * math.cos(math.radians(cy)),
        "bbox": bbox, "source": "Synthetic (network unavailable)",
    }


_DY = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
_DIST = [1.414,1.0,1.414,1.0,1.0,1.414,1.0,1.414]


def compute_flow_direction(dem: np.ndarray) -> np.ndarray:
    rows, cols = dem.shape
    fdir = np.full((rows, cols), -1, dtype=np.int8)
    for r in range(1, rows-1):
        for c in range(1, cols-1):
            max_slope = 0
            best = -1
            for i, (dr, dc) in enumerate(_DY):
                nr, nc = r+dr, c+dc
                drop = dem[r, c] - dem[nr, nc]
                dist = 1.414 if dr and dc else 1.0
                slope = drop / dist
                if slope > max_slope:
                    max_slope = slope
                    best = i
            fdir[r, c] = best
    return fdir


def compute_flow_accumulation(fdir: np.ndarray) -> np.ndarray:
    rows, cols = fdir.shape
    acc = np.ones((rows, cols), dtype=np.float64)
    from collections import deque
    indeg = np.zeros((rows, cols), dtype=np.int32)
    for r in range(rows):
        for c in range(cols):
            d = fdir[r, c]
            if 0 <= d < 8:
                dr, dc = _DY[d]
                nr, nc = r+dr, c+dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    indeg[nr, nc] += 1
    q = deque()
    for r in range(rows):
        for c in range(cols):
            if indeg[r, c] == 0:
                q.append((r, c))
    while q:
        r, c = q.popleft()
        d = fdir[r, c]
        if 0 <= d < 8:
            dr, dc = _DY[d]
            nr, nc = r+dr, c+dc
            if 0 <= nr < rows and 0 <= nc < cols:
                acc[nr, nc] += acc[r, c]
                indeg[nr, nc] -= 1
                if indeg[nr, nc] == 0:
                    q.append((nr, nc))
    return acc


def simulate_flood_2d(
    dem: np.ndarray,
    buildings: list[dict],
    bbox: list[float],
    rainfall_mm: float = 100,
    cn: float = 75,
    duration_h: int = 6,
    dt_min: float = 15,
    manning_n: float = 0.035,
    osm_cn_grid: np.ndarray = None,
) -> dict:
    from .hydro_chain import (
        extract_stream_network, find_stream_nodes,
        assign_distributed_cn, compute_travel_times, route_flow_time_area,
    )

    rows, cols = dem.shape
    cell_m = abs(bbox[2]-bbox[0]) * 111320 / cols
    cell_area_m2 = cell_m * cell_m

    logger.info(f"[flood_2d] DEM {rows}x{cols} cell={cell_m:.0f}m rain={rainfall_mm}mm")

    # ── Step 1: 流域划分 ──
    logger.info("[flood_2d] Step1: Flow direction + accumulation...")
    fdir = compute_flow_direction(dem)
    facc = compute_flow_accumulation(fdir)
    stream = extract_stream_network(fdir, facc)
    nodes = find_stream_nodes(fdir, stream)
    n_streams = int(stream.sum())
    logger.info(f"[flood_2d] Stream cells: {n_streams}, Nodes: {len(nodes)}")

    # ── Step 2: 分布式水文 ──
    logger.info("[flood_2d] Step2: Distributed CN assignment...")
    cn_grid = assign_distributed_cn(dem, fdir, osm_cn_grid)
    s_grid = 25400.0 / cn_grid - 254
    ia_grid = 0.2 * s_grid
    excess_grid = np.where(rainfall_mm > ia_grid,
                           (rainfall_mm - ia_grid)**2 / (rainfall_mm + 0.8*s_grid), 0.0)
    total_runoff_mm = float(excess_grid.mean())
    logger.info(f"[flood_2d] CN range: {cn_grid.min():.0f}-{cn_grid.max():.0f} mean runoff={total_runoff_mm:.1f}mm")

    # ── Step 3: 汇流演算 ──
    logger.info("[flood_2d] Step3: Travel time + flow routing...")
    travel_time = compute_travel_times(dem, fdir, facc, cell_m, manning_n)
    hydro = route_flow_time_area(
        dem, fdir, facc, cn_grid, travel_time,
        rainfall_mm, duration_h, dt_min, cell_m,
    )
    discharge = hydro["discharge_cms"]
    peak_q = hydro["peak_discharge_cms"]
    logger.info(f"[flood_2d] Peak Q={peak_q} m3/s at {hydro['peak_discharge_time']}")

    # ── Step 4: 二维水动力演进 ──
    logger.info("[flood_2d] Step4: 2D hydrodynamic simulation...")
    n_steps = int(duration_h * 60 / dt_min)
    dt = dt_min * 60
    depth = np.zeros((rows, cols), dtype=np.float64)
    peak_step = n_steps // 3

    depth_frames = []
    time_labels = []
    stats_per_step = []

    for step in range(n_steps + 1):
        t_h = step * dt_min / 60

        rf = max(0, 1 - (step - peak_step*2) / max(n_steps - peak_step*2, 1))
        depth += (excess_grid / 1000.0) * rf * dt / (duration_h * 3600)

        q_t = discharge[step] if step < len(discharge) else 0
        if step < peak_step:
            rf = step / max(peak_step, 1)
        elif step < peak_step * 2:
            rf = 1.0
        else:
            rf = max(0, 1 - (step - peak_step*2) / max(n_steps - peak_step*2, 1))
        depth += (excess_grid / 1000.0) * rf * dt / (duration_h * 3600)

        q_t = discharge[step] if step < len(discharge) else 0
        if q_t > 0 and n_streams > 0:
            stream_cells = np.argwhere(stream)
            if len(stream_cells) > 0:
                inject_per_cell = q_t * dt / (n_streams * cell_area_m2)
                for sr, sc in stream_cells:
                    depth[sr, sc] += inject_per_cell * 0.3

        flow = np.zeros_like(depth)
        for r in range(1, rows-1):
            for c in range(1, cols-1):
                if depth[r, c] < 0.001:
                    continue
                outs = []
                for i, (dr, dc) in enumerate(_DY):
                    nr, nc = r+dr, c+dc
                    ds = dem[r,c] + depth[r,c] - (dem[nr,nc] + depth[nr,nc])
                    if ds > 0:
                        v = (1/manning_n) * (max(depth[r,c],0.01)**(2/3)) * math.sqrt(max(ds/_DIST[i], 0.0001))
                        q = v * depth[r,c] * cell_m / 8
                        outs.append((nr, nc, min(q * dt / cell_area_m2, depth[r,c] / 8)))
                if outs:
                    tot = sum(o[2] for o in outs)
                    if tot > depth[r,c]:
                        sc_f = depth[r,c] / tot
                        outs = [(nr,nc,q*sc_f) for nr,nc,q in outs]
                    for nr, nc, q in outs:
                        flow[r, c] -= q
                        flow[nr, nc] += q
        depth += flow
        depth[depth < 0.0005] = 0

        if step % 2 == 0 or step == n_steps:
            max_d = float(depth.max())
            flooded = int((depth > 0.05).sum())
            vol = float(depth.sum() * cell_area_m2)
            depth_frames.append(depth.tolist())
            time_labels.append(f"{t_h:.1f}h")
            stats_per_step.append({
                "time_h": round(t_h, 1), "max_depth_m": round(max_d, 2),
                "flooded_cells": flooded, "flooded_pct": round(flooded/(rows*cols)*100, 1),
                "volume_m3": round(vol, 0),
                "discharge_cms": round(discharge[step], 1) if step < len(discharge) else 0,
            })

    # ── Step 5: 建筑淹没评估 ──
    peak_idx = max(range(len(stats_per_step)), key=lambda i: stats_per_step[i]["max_depth_m"])
    peak_grid = np.array(depth_frames[peak_idx])

    building_impacts = []
    for b in buildings:
        props = b.get("properties", {})
        center = props.get("center", [0, 0])
        col = int((center[0] - bbox[0]) / (bbox[2] - bbox[0]) * (cols-1))
        row = int((bbox[3] - center[1]) / (bbox[3] - bbox[1]) * (rows-1))
        col = max(0, min(cols-1, col))
        row = max(0, min(rows-1, row))
        elev_b = float(dem[row, col])
        height_m = props.get("height_m", 6)
        max_d = float(peak_grid[row, col]) if 0 <= row < rows and 0 <= col < cols else 0
        if max_d >= height_m:
            status = "submerged"
        elif max_d > 0.1:
            status = "partial"
        else:
            status = "safe"
        building_impacts.append({
            "center": center, "elevation_m": round(elev_b, 1),
            "height_m": height_m,
            "building_type": props.get("building_type", "一般建筑"),
            "flood_status": status,
            "max_flood_depth_m": round(max_d, 1),
            "floors_flooded": max(0, int(max_d / 3)),
            "polygon": b.get("geometry", {}).get("coordinates", [[]])[0],
        })

    n_safe = sum(1 for b in building_impacts if b["flood_status"] == "safe")
    n_partial = sum(1 for b in building_impacts if b["flood_status"] == "partial")
    n_submerged = sum(1 for b in building_impacts if b["flood_status"] == "submerged")

    stream_mask = facc > max(facc.mean() * 3, 10)
    return {
        "flood_sim_3d": True,
        "rainfall_mm": rainfall_mm,
        "runoff_mm": round(total_runoff_mm, 1),
        "curve_number": cn,
        "cn_grid_mean": round(float(cn_grid.mean()), 1),
        "cn_grid_range": [round(float(cn_grid.min()), 0), round(float(cn_grid.max()), 0)],
        "duration_h": duration_h, "manning_n": manning_n,
        "depth_frames": depth_frames, "time_labels": time_labels,
        "stats_per_step": stats_per_step,
        "building_impacts": building_impacts,
        "stream_network_cells": n_streams,
        "stream_nodes": len(nodes),
        "stream_density": round(float(stream_mask.sum()) / (rows*cols), 4),
        "flow_accumulation_max": float(facc.max()),
        "discharge_cms": discharge,
        "peak_discharge_cms": peak_q,
        "peak_discharge_time": hydro["peak_discharge_time"],
        "travel_time_max_min": round(hydro["travel_time_max_s"] / 60, 1),
        "travel_time_mean_min": round(hydro["travel_time_mean_s"] / 60, 1),
        "time_area_histogram": hydro["time_area_histogram"],
        "excess_rainfall_grid": excess_grid.tolist(),
        "elevation_grid": dem.tolist(),
        "grid_n": rows, "grid_m": cols,
        "grid_lats": np.linspace(bbox[1], bbox[3], rows).tolist(),
        "grid_lons": np.linspace(bbox[0], bbox[2], cols).tolist(),
        "elev_range": [float(dem.min()), float(dem.max())],
        "bbox": bbox,
        "data_source": "Distributed Hydro + 2D Hydrodynamic",
        "resolution_m": round(cell_m, 0),
        "stats": {
            "total_buildings": len(building_impacts),
            "safe": n_safe, "partial": n_partial, "submerged": n_submerged,
            "max_flooded_area_pct": stats_per_step[peak_idx]["flooded_pct"],
            "peak_depth_m": stats_per_step[peak_idx]["max_depth_m"],
            "peak_time_h": stats_per_step[peak_idx]["time_h"],
            "peak_q_cms": peak_q,
        },
    }
