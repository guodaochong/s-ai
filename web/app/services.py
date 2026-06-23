from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import structlog

from app.config import logger
from app.utils import bbox_overlap
from app.knowledge import geocode_city







_recon_engine = None

_last_flood_result: dict | None = None
_last_flood_time: float = 0
_last_flood_bbox: list[float] | None = None


def get_recon_engine():
    global _recon_engine
    if _recon_engine is None:
        import sys as _sys
        from app.config import RECON_DIR
        _recon_path = str(RECON_DIR)
        if _recon_path not in _sys.path:
            _sys.path.insert(0, _recon_path)
        from reconstruct.engine import ReconstructionEngine
        _recon_engine = ReconstructionEngine.get_instance()
    return _recon_engine


def generate_default_waypoints(bbox, mission_type):
    import math
    west, south, east, north = bbox
    n = 8
    hotspots = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        r = 0.3
        lat = (south + north) / 2 + r * (north - south) / 2 * math.sin(angle)
        lon = (west + east) / 2 + r * (east - west) / 2 * math.cos(angle)
        hotspots.append({"lat": lat, "lon": lon, "type": "survey", "risk_score": 5, "label": f"巡查点{i+1}"})
    return hotspots



async def run_multi_agent_debate(scenario: str):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from multi_agent.engine import run_multi_agent_debate

    logger.info(f"[debate] Starting multi-agent debate: {scenario[:80]}")
    result = await run_multi_agent_debate(call_llm, scenario, rounds=3)
    logger.info(f"[debate] Done: {result['n_agents']} agents, {result['rounds']} rounds")
    return result


async def extract_buildings(bbox=None, location=None):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from segment.osm_buildings import fetch_osm_buildings

    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        if location:
            coord = await geocode_city(location)
            if coord:
                cx, cy = coord
                half = 0.0075
                bbox = [cx - half, cy - half, cx + half, cy + half]
                logger.info(f"[building_extract] Geocoded '{location}' -> ({cx:.4f}, {cy:.4f})")
        if not bbox:
            bbox = [105.725, 34.580, 105.745, 34.595]
    west, south, east, north = bbox

    max_span = 0.02
    cx, cy = (west + east) / 2, (south + north) / 2
    if abs(east - west) > max_span or abs(north - south) > max_span:
        west = cx - max_span / 2
        east = cx + max_span / 2
        south = cy - max_span / 2
        north = cy + max_span / 2
    bbox = [west, south, east, north]

    logger.info(f"[building_extract] Querying OSM buildings bbox={bbox}")
    try:
        features = await fetch_osm_buildings(bbox)
    except Exception as e:
        logger.warning(f"[building_extract] OSM failed: {e}, falling back to SAM")
        features = []

    if len(features) < 3:
        logger.info(f"[building_extract] OSM only {len(features)} buildings, falling back to SAM")
        from segment.tile_fetcher import fetch_tiles_for_bbox
        from segment.engine import segment_buildings
        zoom = 18
        tile_data = await fetch_tiles_for_bbox(west, south, east, north, zoom=zoom)
        result = await asyncio.to_thread(segment_buildings, tile_data["image"], tile_data["bbox"])
        result["data_source"] = "ArcGIS World Imagery + SAM vit_b (fallback)"
        result["zoom"] = tile_data["zoom"]
        result["n_tiles"] = tile_data["n_tiles"]
    else:
        avg_h = sum(f["properties"]["height_m"] for f in features) / len(features)
        total_a = sum(f["properties"]["area_m2"] for f in features)
        result = {
            "buildings": features,
            "count": len(features),
            "avg_height_m": round(avg_h, 1),
            "total_area_m2": round(total_a, 1),
            "bbox": bbox,
            "image_size": [0, 0],
            "data_source": "OpenStreetMap (精确轮廓)",
            "zoom": 18,
            "n_tiles": 0,
        }

    result["building_extract"] = True
    logger.info(f"[building_extract] Done: {result['count']} buildings from {result.get('data_source','?')}")
    return result


async def monitor_water(bbox=None, location=None):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from water_monitor.engine import search_scenes, extract_water

    if location:
        coord = await geocode_city(location)
        if coord:
            cx, cy = coord
            half = 0.05
            bbox = [cx - half, cy - half, cx + half, cy + half]
            logger.info(f"[water_monitor] Geocoded '{location}' -> ({cx:.4f}, {cy:.4f})")
    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        bbox = [104.85, 33.15, 105.05, 33.35]

    logger.info(f"[water_monitor] Searching Sentinel-2 scenes for bbox={bbox}")
    scenes = await search_scenes(bbox, max_cloud=20, limit=30)
    if not scenes:
        return {"error": "未找到覆盖该区域的低云量Sentinel-2影像，请尝试其他日期范围或区域"}

    logger.info(f"[water_monitor] Found {len(scenes)} scenes, best: {scenes[0]['date']} cloud={scenes[0]['cloud']:.1f}%")
    result = await asyncio.to_thread(extract_water, bbox, scenes[0])
    result["water_monitor"] = True
    result["data_source"] = "Sentinel-2 L2A (10m)"
    result["satellite"] = scenes[0]["scene_id"]
    result["available_dates"] = [s["date"] for s in scenes[:5]]

    logger.info(f"[water_monitor] Done: {result['water_body_count']} water bodies, {result['total_water_area_km2']}km2")
    return result


async def detect_water_change(bbox=None, location=None, date1="", date2=""):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from water_monitor.engine import search_scenes, detect_water_change

    if location:
        coord = await geocode_city(location)
        if coord:
            cx, cy = coord
            half = 0.05
            bbox = [cx - half, cy - half, cx + half, cy + half]
            logger.info(f"[water_change] Geocoded '{location}' -> ({cx:.4f}, {cy:.4f})")
    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        bbox = [104.85, 33.15, 105.05, 33.35]

    if date1 and len(date1) >= 7:
        y1, m1 = date1[:4], date1[5:7]
        range1_start = f"{y1}-{m1}-01"
        range1_end = f"{y1}-{m1}-28"
    else:
        range1_start, range1_end = "2024-06-01", "2024-07-31"

    if date2 and len(date2) >= 7:
        y2, m2 = date2[:4], date2[5:7]
        range2_start = f"{y2}-{m2}-01"
        range2_end = f"{y2}-{m2}-28"
    else:
        range2_start, range2_end = "2024-09-01", "2024-10-31"

    logger.info(f"[water_change] bbox={bbox} period1={range1_start}~{range1_end} period2={range2_start}~{range2_end}")
    scenes1 = await search_scenes(bbox, date_start=range1_start, date_end=range1_end, max_cloud=15)
    scenes2 = await search_scenes(bbox, date_start=range2_start, date_end=range2_end, max_cloud=15)

    if not scenes1:
        scenes1 = await search_scenes(bbox, date_start=range1_start, date_end=range1_end, max_cloud=30)
    if not scenes2:
        scenes2 = await search_scenes(bbox, date_start=range2_start, date_end=range2_end, max_cloud=30)

    if not scenes1 or not scenes2:
        return {"error": f"未找到足够低云量的Sentinel-2影像覆盖两个时期({range1_start[:7]} / {range2_start[:7]})，请尝试其他月份"}

    logger.info(f"[water_change] Period1: {scenes1[0]['date']} Period2: {scenes2[0]['date']}")
    result = detect_water_change(bbox, scenes1[0], scenes2[0])
    logger.info(f"[water_change] Done: {result['area1_km2']}->{result['area2_km2']}km2 ({result['change_pct']:+.1f}%)")
    return result


async def simulate_flood_3d(bbox=None, location=None, rainfall_mm=100):
    import sys
    import numpy as np
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from flood_sim.engine import fetch_elevation_grid, simulate_flood_2d
    from segment.osm_buildings import fetch_osm_buildings, fetch_landuse, sample_cn_from_landuse

    if location:
        coord = await geocode_city(location)
        if coord:
            cx, cy = coord
            half = 0.015
            bbox = [cx - half, cy - half, cx + half, cy + half]
            logger.info(f"[flood_sim_3d] Geocoded '{location}' -> ({cx:.4f}, {cy:.4f})")
    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        bbox = [105.72, 34.57, 105.75, 34.60]

    logger.info(f"[flood_sim_3d] bbox={bbox} rainfall={rainfall_mm}mm")

    elev_data = await fetch_elevation_grid(bbox, grid_n=40)

    try:
        buildings = await fetch_osm_buildings(bbox)
    except Exception as e:
        logger.warning(f"[flood_sim_3d] OSM buildings fetch failed: {e}")
        buildings = []

    osm_cn_grid = None
    try:
        landuse_polys = await fetch_landuse(bbox)
        if landuse_polys:
            grid_lats = np.linspace(bbox[1], bbox[3], elev_data["grid_n"]).tolist()
            grid_lons = np.linspace(bbox[0], bbox[2], elev_data.get("grid_m", elev_data["grid_n"])).tolist()
            osm_cn_grid = sample_cn_from_landuse(landuse_polys, grid_lats, grid_lons)
            logger.info(f"[flood_sim_3d] OSM landuse CN: {len(landuse_polys)} polygons sampled")
    except Exception as e:
        logger.warning(f"[flood_sim_3d] Landuse fetch failed: {e}")

    result = simulate_flood_2d(
        np.array(elev_data["grid"]),
        buildings,
        bbox,
        rainfall_mm=float(rainfall_mm or 100),
        osm_cn_grid=osm_cn_grid,
    )

    result["flood_sim_3d"] = True
    result["elevation_grid"] = elev_data["grid"]
    result["grid_n"] = elev_data["grid_n"]
    result["grid_lats"] = elev_data["lats"]
    result["grid_lons"] = elev_data["lons"]
    result["elev_range"] = [elev_data["min_elev"], elev_data["max_elev"]]
    result["bbox"] = bbox
    result["data_source"] = f"2D Hydrodynamic + {elev_data.get('source', 'DEM')}"
    result["location"] = location or ""

    logger.info(f"[flood_sim_3d] Done: {result['stats']['safe']}safe/{result['stats']['partial']}partial/{result['stats']['submerged']}submerged")

    global _last_flood_result, _last_flood_time, _last_flood_bbox
    _last_flood_result = result
    _last_flood_time = time.time()
    _last_flood_bbox = bbox
    return result


async def plan_drone_mission(bbox=None, location=None, mission_type="flood_inspect"):
    import sys
    import numpy as np
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from drone.mission import identify_risk_hotspots, plan_mission, MISSION_PROFILES

    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        if location:
            coord = await geocode_city(location)
            if coord:
                cx, cy = coord
                half = 0.015
                bbox = [cx - half, cy - half, cx + half, cy + half]
        if not bbox:
            bbox = [105.71, 34.57, 105.74, 34.60]

    logger.info(f"[drone_mission] Planning {mission_type} for bbox={bbox}")

    flood_result = None
    global _last_flood_result, _last_flood_time, _last_flood_bbox
    if (_last_flood_result and _last_flood_bbox and
        time.time() - _last_flood_time < 300 and
        bbox_overlap(_last_flood_bbox, bbox)):
        logger.info("[drone_mission] Reusing recent flood simulation result")
        flood_result = _last_flood_result
    else:
        try:
            logger.info("[drone_mission] Running flood simulation for risk assessment...")
            flood_result = await simulate_flood_3d(bbox, location, 150)
            if "error" in flood_result:
                flood_result = None
        except Exception as e:
            logger.warning(f"[drone_mission] Flood sim failed: {e}")

    if flood_result and flood_result.get("building_impacts"):
        impacts = flood_result["building_impacts"]
        depth_frames = flood_result.get("depth_frames", [])
        if depth_frames:
            peak_idx = max(range(len(depth_frames)), key=lambda i: max(max(r) for r in depth_frames[i]) if depth_frames[i] else 0)
            depth_grid = depth_frames[peak_idx] if peak_idx < len(depth_frames) else depth_frames[-1]
        else:
            depth_grid = []

        grid_lats = flood_result.get("grid_lats", [])
        grid_lons = flood_result.get("grid_lons", [])

        hotspots = identify_risk_hotspots(impacts, depth_grid, grid_lats, grid_lons, bbox)
        logger.info(f"[drone_mission] Found {len(hotspots)} risk hotspots from flood sim")
    else:
        hotspots = generate_default_waypoints(bbox, mission_type)

    result = plan_mission(hotspots, bbox, mission_type)
    result["flood_summary"] = {
        "rainfall_mm": flood_result.get("rainfall_mm") if flood_result else 0,
        "peak_depth_m": flood_result.get("stats", {}).get("peak_depth_m") if flood_result else 0,
        "flooded_pct": flood_result.get("stats", {}).get("max_flooded_area_pct") if flood_result else 0,
        "buildings_at_risk": (flood_result.get("stats", {}).get("partial", 0) + flood_result.get("stats", {}).get("submerged", 0)) if flood_result else 0,
    } if flood_result else None

    logger.info(f"[drone_mission] Done: {result['n_waypoints']} waypoints, {result['total_distance_km']}km, {result['estimated_flight_min']}min")
    return result
