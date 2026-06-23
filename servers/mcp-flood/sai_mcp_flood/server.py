from __future__ import annotations

import json
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

logger = structlog.get_logger(__name__)


async def flood_assessment(
    area_name: str = "demo_area",
    rainfall_mm: float = 100.0,
    drainage_area_ha: float = 20.0,
    impervious_pct: float = 65.0,
    pipe_capacity_cms: float = 2.0,
    dem_elevation_range: tuple[float, float] | None = None,
) -> dict[str, Any]:
    runoff_mm = max(0, (rainfall_mm - rainfall_mm * (1 - impervious_pct / 100) * 0.3)) * impervious_pct / 100 * 0.9
    runoff_volume = runoff_mm / 1000 * drainage_area_ha * 10000
    peak_inflow = rainfall_mm / 3600 / 1000 * drainage_area_ha * 10000 * impervious_pct / 100 * 0.9
    overflow_volume = max(0, runoff_volume - pipe_capacity_cms * 3600)
    flood_depth_avg = overflow_volume / (drainage_area_ha * 10000) * 100 if drainage_area_ha > 0 else 0

    if flood_depth_avg < 5:
        risk = "low"
    elif flood_depth_avg < 15:
        risk = "medium"
    elif flood_depth_avg < 30:
        risk = "high"
    else:
        risk = "critical"

    return {
        "area_name": area_name,
        "rainfall_mm": rainfall_mm,
        "runoff_mm": round(runoff_mm, 2),
        "runoff_volume_m3": round(runoff_volume, 1),
        "peak_inflow_cms": round(peak_inflow, 3),
        "pipe_capacity_cms": pipe_capacity_cms,
        "overflow_volume_m3": round(overflow_volume, 1),
        "avg_flood_depth_cm": round(flood_depth_avg, 1),
        "risk_level": risk,
        "affected_area_ha": round(overflow_volume / (flood_depth_avg / 100) if flood_depth_avg > 0 else 0, 2),
    }


async def flood_inundation_map(
    center_lng: float = 104.8904,
    center_lat: float = 33.1854,
    radius_m: float = 2000.0,
    max_depth_m: float = 0.5,
    water_level_m: float | None = None,
    rainfall_mm: float = 100.0,
    dem_path: str = "",
) -> dict[str, Any]:
    import math
    import json as _json
    from pathlib import Path

    import numpy as np
    from skimage.measure import find_contours

    dem_data_dir = Path(__file__).parent.parent.parent.parent / "data"
    real_dem = dem_data_dir / "LBH_DEM_v2_0.5m_EPSG4544.tif"
    dem_npy = dem_data_dir / "dem_beijing.npy"
    dem_meta = dem_data_dir / "dem_beijing_meta.json"

    if real_dem.exists() and dem_path != "synthetic":
        import rasterio
        from rasterio.transform import rowcol
        from pyproj import Transformer
        ds = rasterio.open(str(real_dem))
        t_crs = ds.crs
        to_wgs84 = Transformer.from_crs("EPSG:4326", t_crs, always_xy=True)
        to_wgs84_back = Transformer.from_crs(t_crs, "EPSG:4326", always_xy=True)
        px_size = abs(ds.transform[0])

        # Try user coordinates first; if nodata, sample DEM center for valid region
        cx, cy = to_wgs84.transform(center_lng, center_lat)
        row_c, col_c = ds.index(cx, cy)
        test_win = rasterio.windows.Window(
            max(0, col_c - 50), max(0, row_c - 50),
            min(100, ds.width - max(0, col_c - 50)),
            min(100, ds.height - max(0, row_c - 50)))
        test_data = ds.read(1, window=test_win)
        nodata_val = ds.nodata if ds.nodata is not None else -9999
        valid_pct = float((test_data != nodata_val).sum()) / test_data.size
        if valid_pct < 0.3:
            # User coords in nodata zone — find densest valid cluster via 50x50 patches
            patch = 50
            best_density = 0
            best_rc = (ds.height // 2, ds.width // 2)
            for rr in range(0, ds.height - patch, patch * 2):
                for cc in range(0, ds.width - patch, patch * 2):
                    w = ds.read(1, window=rasterio.windows.Window(cc, rr, patch, patch))
                    density = float((w != nodata_val).sum()) / w.size
                    if density > best_density:
                        best_density = density
                        best_rc = (rr + patch // 2, cc + patch // 2)
            if best_density < 0.1:
                return _inundation_fallback(center_lng, center_lat, radius_m, max_depth_m)
            row_c, col_c = best_rc
            px, py = ds.transform * (col_c, row_c)
            center_lng, center_lat = to_wgs84_back.transform(px, py)

        raw_half = int(radius_m / px_size)
        max_half = 1500
        win_half = min(raw_half, max_half)
        win = None
        try:
            from rasterio.windows import Window
            x0 = max(0, col_c - win_half)
            y0 = max(0, row_c - win_half)
            w = min(win_half * 2, ds.width - x0)
            h = min(win_half * 2, ds.height - y0)
            win = Window(x0, y0, w, h)
        except Exception as exc:
            logger.warning("[Flood] windowed read failed, falling back to full dataset", error=str(exc)[:200])
        out_h = min(800, win.height if win else ds.height)
        out_w = min(800, win.width if win else ds.width)
        if win:
            fdata = ds.read(1, window=win, out_shape=(out_h, out_w))
        else:
            fdata = ds.read(1, out_shape=(out_h, out_w))
        fdata = fdata.astype(np.float32)
        mask = (fdata == nodata_val)
        valid_count = int((~mask).sum())
        if valid_count == 0:
            ds.close()
            return _inundation_fallback(center_lng, center_lat, radius_m, max_depth_m)
        rt = ds.window_transform(win) if win else ds.transform
        if win and (out_w != win.width or out_h != win.height):
            from rasterio.transform import Affine
            rt = rt * Affine.scale(win.width / out_w, win.height / out_h)
        rows, cols = fdata.shape
        nw_x, nw_y = rt * (0, 0)
        se_x, se_y = rt * (cols, rows)
        lng_min_o, lat_max_o = to_wgs84_back.transform(nw_x, nw_y)
        lng_max_o, lat_min_o = to_wgs84_back.transform(se_x, se_y)
        nx, ny = rows, cols
        cell_lng = (lng_max_o - lng_min_o) / cols
        cell_lat = (lat_max_o - lat_min_o) / rows
        lng_min, lat_min = lng_min_o, lat_min_o
        lng_max, lat_max = lng_max_o, lat_max_o
        dem = fdata
        real_dem_used = True
        valid_mask = ~mask
        ds.close()
    elif dem_npy.exists():
        dem = np.load(str(dem_npy))
        valid_mask = np.ones_like(dem, dtype=bool)
        with open(str(dem_meta)) as f:
            meta = _json.load(f)
        nx, ny = meta["nx"], meta["ny"]
        lng_min, lat_min = meta["lng_min"], meta["lat_min"]
        lng_max, lat_max = meta["lng_max"], meta["lat_max"]
        cell_lng = (lng_max - lng_min) / nx
        cell_lat = (lat_max - lat_min) / ny
        real_dem_used = False
    else:
        return _inundation_fallback(center_lng, center_lat, radius_m, max_depth_m)

    if water_level_m is None:
        valid_elevs = dem[valid_mask]
        if valid_elevs.size == 0:
            return _inundation_fallback(center_lng, center_lat, radius_m, max_depth_m)
        base_elev = float(valid_elevs.min())
        water_level_m = base_elev + max_depth_m

    depth_map = water_level_m - dem
    depth_map[~valid_mask] = -1
    depth_map[depth_map < 0] = 0
    flooded = depth_map > 0
    n_flooded = int(flooded.sum())
    if n_flooded == 0:
        return {"center": [center_lng, center_lat], "water_level_m": water_level_m, "flooded_cells": 0,
                "total_flood_area_m2": 0, "geojson": {"type": "FeatureCollection", "features": []}}

    actual_max_depth = float(depth_map[flooded].max())
    n_levels = min(5, max(2, int(actual_max_depth / 1.0)))
    depth_thresholds = [actual_max_depth * (i + 1) / n_levels for i in range(n_levels)]
    depth_thresholds.reverse()

    features = []
    for level_idx, thresh in enumerate(depth_thresholds):
        mask = depth_map >= thresh
        if not mask.any():
            continue
        mask_uint8 = mask.astype(np.uint8)
        contours = find_contours(mask_uint8, 0.5)
        if not contours:
            continue
        contour = max(contours, key=len)
        if len(contour) < 4:
            continue
        step = max(1, len(contour) // 60)
        sampled = contour[::step]
        coords = []
        for row, col in sampled:
            lng = lng_min + col * cell_lng
            lat = lat_max - row * cell_lat
            coords.append([round(lng, 6), round(lat, 6)])
        if coords:
            coords.append(coords[0])
        depth_val = thresh
        features.append({
            "type": "Feature",
            "properties": {"depth_m": round(depth_val, 2), "level": level_idx + 1},
            "geometry": {"type": "Polygon", "coordinates": [coords]},
        })

    cell_area_m2 = (cell_lng * 111000) * (cell_lat * 111000)
    total_area = round(n_flooded * cell_area_m2, 1)
    avg_depth = round(float(depth_map[flooded].mean()), 2)
    max_actual_depth = round(float(depth_map.max()), 2)

    return {
        "center": [center_lng, center_lat],
        "water_level_m": round(water_level_m, 2),
        "dem_source": "LBH_DEM_v2_0.5m_EPSG4544.tif" if real_dem_used else "dem_beijing.npy",
        "flooded_cells": n_flooded,
        "total_cells": nx * ny,
        "flood_pct": round(n_flooded / (nx * ny) * 100, 1),
        "avg_depth_m": avg_depth,
        "max_depth_m": max_actual_depth,
        "total_flood_area_m2": total_area,
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def _inundation_fallback(center_lng, center_lat, radius_m, max_depth_m):
    import math
    n_rings = 5
    rings = []
    for i in range(n_rings):
        r = radius_m * (i + 1) / n_rings
        depth = max_depth_m * (1 - (i / n_rings) ** 0.5)
        coords = []
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            lng = center_lng + r * math.cos(rad) / 111000 / math.cos(math.radians(center_lat))
            lat = center_lat + r * math.sin(rad) / 111000
            coords.append([round(lng, 6), round(lat, 6)])
        coords.append(coords[0])
        rings.append({"ring": i + 1, "radius_m": round(r, 1), "depth_m": round(depth, 3),
                       "polygon_geojson": {"type": "Polygon", "coordinates": [coords]}})
    return {"center": [center_lng, center_lat], "radius_m": radius_m, "max_depth_m": max_depth_m,
            "rings": rings, "total_flood_area_m2": round(math.pi * radius_m ** 2, 1),
            "geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"depth_m": r["depth_m"], "ring": r["ring"]},
                 "geometry": r["polygon_geojson"]} for r in rings]}}


async def flood_risk_zones(
    area_geojson: dict | None = None,
    population_density: float = 5000.0,
    infrastructure_density: float = 0.3,
) -> dict[str, Any]:
    zones = [
        {"zone": "Z1_critical", "risk": "critical", "description": "low_elevation + dense_infrastructure", "area_pct": 8, "population_affected_pct": 15},
        {"zone": "Z2_high", "risk": "high", "description": "low_elevation + moderate_infrastructure", "area_pct": 18, "population_affected_pct": 25},
        {"zone": "Z3_medium", "risk": "medium", "description": "moderate_elevation + dense_infrastructure", "area_pct": 30, "population_affected_pct": 35},
        {"zone": "Z4_low", "risk": "low", "description": "high_elevation_or_sparse", "area_pct": 44, "population_affected_pct": 25},
    ]
    return {
        "population_density_per_km2": population_density,
        "infrastructure_density": infrastructure_density,
        "zones": zones,
        "total_population_at_risk": round(population_density * (1 - zones[3]["population_affected_pct"] / 100), 0),
    }


async def drainage_assessment(
    pipe_diameter_m: float = 0.8,
    pipe_slope: float = 0.003,
    manning_n: float = 0.013,
    design_flow_cms: float = 1.5,
    pipe_length_m: float = 500.0,
) -> dict[str, Any]:
    import math

    a = math.pi * (pipe_diameter_m / 2) ** 2
    r_h = pipe_diameter_m / 4
    v = (1 / manning_n) * r_h ** (2 / 3) * pipe_slope ** 0.5
    q_full = v * a
    capacity_ratio = q_full / design_flow_cms if design_flow_cms > 0 else 0
    travel_time_min = pipe_length_m / v / 60 if v > 0 else 0

    return {
        "pipe_diameter_m": pipe_diameter_m,
        "full_flow_velocity_m_s": round(v, 3),
        "full_flow_capacity_cms": round(q_full, 3),
        "design_flow_cms": design_flow_cms,
        "capacity_ratio": round(capacity_ratio, 3),
        "status": "adequate" if capacity_ratio >= 1.0 else "undersized",
        "deficit_cms": round(max(0, design_flow_cms - q_full), 3),
        "travel_time_min": round(travel_time_min, 1),
    }


async def flood_warning(
    area_name: str = "demo_area",
    current_rainfall_mm_hr: float = 60.0,
    forecast_rainfall_mm_hr: float = 80.0,
    soil_saturation_pct: float = 70.0,
    drainage_utilization_pct: float = 85.0,
) -> dict[str, Any]:
    score = 0
    if current_rainfall_mm_hr > 50:
        score += 30
    if forecast_rainfall_mm_hr > 70:
        score += 25
    if soil_saturation_pct > 60:
        score += 20
    if drainage_utilization_pct > 80:
        score += 25

    if score < 30:
        level, color = "blue", "#4488ff"
    elif score < 50:
        level, color = "yellow", "#ffcc00"
    elif score < 70:
        level, color = "orange", "#ff8800"
    else:
        level, color = "red", "#ff0000"

    actions = {
        "blue": ["monitor_weather", "check_drainage"],
        "yellow": ["alert_maintenance_crews", "clear_drain_inlets", "monitor_gauges"],
        "orange": ["deploy_pumps", "close_underpasses", "alert_emergency_services", "issue_public_advisory"],
        "red": ["activate_emergency_plan", "evacuate_low_areas", "deploy_all_pumps", "issue_flood_warning"],
    }

    return {
        "area": area_name,
        "warning_level": level,
        "color": color,
        "risk_score": score,
        "current_rainfall_mm_hr": current_rainfall_mm_hr,
        "forecast_rainfall_mm_hr": forecast_rainfall_mm_hr,
        "soil_saturation_pct": soil_saturation_pct,
        "drainage_utilization_pct": drainage_utilization_pct,
        "recommended_actions": actions[level],
    }


async def hydrodynamic_2d_sim(
    lng_min: float = 0,
    lng_max: float = 0,
    lat_min: float = 0,
    lat_max: float = 0,
    rainfall_mm: float = 100.0,
    duration_hr: float = 24.0,
    time_step_min: float = 30.0,
    manning_n: float = 0.05,
    infiltration_mm_hr: float = 2.0,
    output_steps: int = 12,
    rain_pattern: str = "uniform",
) -> dict[str, Any]:
    import math
    from pathlib import Path
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    from rasterio.transform import Affine
    from pyproj import Transformer
    from skimage.measure import find_contours

    dem_data_dir = Path(__file__).parent.parent.parent.parent / "data"
    real_dem = dem_data_dir / "LBH_DEM_v2_0.5m_EPSG4544.tif"
    if not real_dem.exists():
        return {"error": "Real DEM not available"}

    with rasterio.open(str(real_dem)) as ds:
        to_wgs = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)
        nd = ds.nodata if ds.nodata is not None else -9999

        patch = 300
        best_score = 1e18
        best_rc = (ds.height // 2, ds.width // 2)
        best_density = 0
        vr_min, vr_max, vc_min, vc_max = ds.height, 0, ds.width, 0
        for rr in range(0, ds.height - patch, patch):
            for cc in range(0, ds.width - patch, patch):
                w = ds.read(1, window=rasterio.windows.Window(cc, rr, patch, patch))
                valid_mask = w != nd
                density = float(valid_mask.sum()) / w.size
                if density < 0.4:
                    continue
                vr_min = min(vr_min, rr); vr_max = max(vr_max, rr + patch)
                vc_min = min(vc_min, cc); vc_max = max(vc_max, cc + patch)
                v = w[valid_mask]
                min_elev = float(v.min())
                score = min_elev - density * 200
                if score < best_score:
                    best_score = score
                    best_rc = (rr + patch // 2, cc + patch // 2)
                    best_density = density

        if best_density < 0.1:
            return {"error": "No valid DEM data region found"}

        row_c, col_c = best_rc
        sim_half = min(8000, ds.width // 3, ds.height // 3)
        col0 = max(vc_min, col_c - sim_half)
        col1 = min(vc_max, col_c + sim_half)
        row0 = max(vr_min, row_c - sim_half)
        row1 = min(vr_max, row_c + sim_half)

        lng_min_wgs, lat_min_wgs = to_wgs.transform(*(ds.transform * (col0, row1)))
        lng_max_wgs, lat_max_wgs = to_wgs.transform(*(ds.transform * (col1, row0)))
        n_full_cols = col1 - col0 + 1
        n_full_rows = row1 - row0 + 1
        max_size = 500
        sub_step = max(1, int(max(n_full_cols, n_full_rows) / max_size))
        out_h = n_full_rows // sub_step
        out_w = n_full_cols // sub_step
        win = Window(col0, row0, n_full_cols, n_full_rows)
        from rasterio.enums import Resampling
        dem = ds.read(1, window=win, out_shape=(out_h, out_w), resampling=Resampling.nearest).astype(np.float64)
        win_transform = ds.window_transform(win)
        sx = n_full_cols / out_w
        sy = n_full_rows / out_h
        rt = win_transform * Affine.scale(sx, sy)
        mask = (dem == nd) | np.isnan(dem)
        if mask.all():
            return {"error": "All nodata"}
        # Don't fill nodata with mean — set to very high elevation so water won't flow there
        if mask.any():
            valid_max = float(dem[~mask].max())
            dem[mask] = valid_max + 2000.0
        cell_x = abs(rt[0]) * sub_step
        cell_y = abs(rt[4]) * sub_step
        cell_area = cell_x * cell_y
        rows, cols = dem.shape

        Z = dem
        H = np.zeros_like(Z)

        # Seed river channel: bottom 5% elevation cells get initial water depth
        valid_elevs = Z[~mask]
        p3 = float(np.percentile(valid_elevs, 3))
        river_mask = (Z <= p3) & (~mask)
        H[river_mask] = 0.3
        # Clear boundary cells (keep interior river only)
        H[0, :] = 0.0
        H[-1, :] = 0.0
        H[:, 0] = 0.0
        H[:, -1] = 0.0

        wet = H > 1e-5
        valid_z = Z[~mask]
        elev_min = float(valid_z.min())
        elev_max = float(valid_z.max())

        total_minutes = int(duration_hr * 60)
        dt_min_target = max(1, int(time_step_min))
        n_steps_target = max(2, int(total_minutes / dt_min_target))
        if n_steps_target > 144:
            n_steps_target = 144

        rain_rate_mps = (rainfall_mm / max(duration_hr, 0.1)) / 1000.0 / 3600.0
        infil_mps = infiltration_mm_hr / 1000.0 / 3600.0
        net_rain_mps = max(0.0, rain_rate_mps - infil_mps)

        dt_s = dt_min_target * 60.0
        hyeto = np.full(n_steps_target, net_rain_mps)
        if rain_pattern == "triangular":
            peak_step = int(n_steps_target * 0.4)
            for i in range(n_steps_target):
                if i <= peak_step:
                    hyeto[i] = net_rain_mps * (i + 1) / max(peak_step, 1) * 2.0
                else:
                    hyeto[i] = net_rain_mps * max(0, 1.0 - (i - peak_step) / max(n_steps_target - peak_step, 1)) * 2.0
            total_depth = hyeto.sum() * dt_s
            if total_depth > 1e-9:
                hyeto *= (rainfall_mm / 1000.0) / total_depth
        elif rain_pattern == "chicago":
            r_frac = 0.4
            peak_step = int(n_steps_target * r_frac)
            t_arr = np.arange(n_steps_target, dtype=np.float64)
            if 0 < peak_step < n_steps_target - 1:
                pre = t_arr[:peak_step + 1]
                post = t_arr[peak_step:]
                shape_pre = (pre / max(peak_step, 1)) ** 0.5
                shape_post = ((n_steps_target - 1 - post) / max(n_steps_target - 1 - peak_step, 1)) ** 0.5
                hyeto = np.empty(n_steps_target)
                hyeto[:peak_step + 1] = shape_pre
                hyeto[peak_step:] = shape_post
            total_depth = hyeto.sum() * dt_s
            if total_depth > 1e-9:
                hyeto *= (rainfall_mm / 1000.0) / total_depth

        n_steps = n_steps_target
        out_indices = sorted(set(np.linspace(0, n_steps - 1, min(output_steps, n_steps)).astype(int)))

        # Pre-build TIN structure (points + Delaunay, computed once)
        from scipy.spatial import Delaunay as _Delaunay
        import json as _json
        valid_rc = np.argwhere(~mask)
        if len(valid_rc) > 3000:
            idx_sel = np.random.choice(len(valid_rc), 3000, replace=False)
            valid_rc = valid_rc[idx_sel]
        tin_z_arr = np.array([Z[r, c] for r, c in valid_rc])
        tin_lng_arr = np.zeros(len(valid_rc))
        tin_lat_arr = np.zeros(len(valid_rc))
        for ti, (r, c) in enumerate(valid_rc):
            x_pt, y_pt = rt * (c, r)
            tin_lng_arr[ti], tin_lat_arr[ti] = to_wgs.transform(x_pt, y_pt)
        pts2d = np.column_stack([tin_lng_arr, tin_lat_arr])
        tri_obj = _Delaunay(pts2d)
        simp_areas = []
        for simp in tri_obj.simplices:
            x0, y0 = pts2d[simp[0]]; x1, y1 = pts2d[simp[1]]; x2, y2 = pts2d[simp[2]]
            simp_areas.append(abs((x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)) / 2)
        area_med = float(np.median(simp_areas))
        area_max = area_med * 8
        valid_simps = [(i, simp) for i, (simp, a) in enumerate(zip(tri_obj.simplices, simp_areas)) if a <= area_max]

        frames: list[dict[str, Any]] = []
        peak_max = 0.0
        peak_total = 0.0
        cum_rain_mm = 0.0
        mass_balance_initial = 0.0

        hyeto_mps = np.where(hyeto > 0, hyeto - infil_mps, 0.0)

        for step in range(n_steps):
            R = hyeto_mps[step] if step < len(hyeto_mps) else 0.0
            H += R * (dt_min_target * 60)
            cum_rain_mm += R * (dt_min_target * 60) * 1000.0

            eta = Z + H

            qx_face = np.zeros((rows, cols + 1))
            qy_face = np.zeros((rows + 1, cols))

            for c in range(1, cols):
                eta_L = eta[:, c - 1]
                eta_R = eta[:, c]
                h_L = np.maximum(eta_L - Z[:, c - 1], 0)
                h_R = np.maximum(eta_R - Z[:, c], 0)
                h_max = np.maximum(h_L, h_R)
                dhdx = (eta_R - eta_L) / cell_x
                Sf = -dhdx
                q_face = np.where(
                    (h_max > 1e-6) & (np.abs(Sf) > 1e-9),
                    np.sign(Sf) * (h_max ** (5.0 / 3.0)) / manning_n * np.sqrt(np.abs(Sf)),
                    0.0
                )
                CFL_limit = h_max * cell_x / (dt_min_target * 60 + 1e-9)
                q_face = np.clip(q_face, -CFL_limit, CFL_limit)
                qx_face[:, c] = q_face

            for r in range(1, rows):
                eta_T = eta[r - 1, :]
                eta_B = eta[r, :]
                h_T = np.maximum(eta_T - Z[r - 1, :], 0)
                h_B = np.maximum(eta_B - Z[r, :], 0)
                h_max = np.maximum(h_T, h_B)
                dhdy = (eta_B - eta_T) / cell_y
                Sf = -dhdy
                q_face = np.where(
                    (h_max > 1e-6) & (np.abs(Sf) > 1e-9),
                    np.sign(Sf) * (h_max ** (5.0 / 3.0)) / manning_n * np.sqrt(np.abs(Sf)),
                    0.0
                )
                CFL_limit = h_max * cell_y / (dt_min_target * 60 + 1e-9)
                q_face = np.clip(q_face, -CFL_limit, CFL_limit)
                qy_face[r, :] = q_face

            dqx_dx = (qx_face[:, 1:] - qx_face[:, :-1]) / cell_x
            dqy_dy = (qy_face[1:, :] - qy_face[:-1, :]) / cell_y

            H -= (dqx_dx + dqy_dy) * (dt_min_target * 60)
            H = np.maximum(H, 0.0)
            H[0, :] = 0.0
            H[-1, :] = 0.0
            H[:, 0] = 0.0
            H[:, -1] = 0.0
            H[mask] = 0.0
            H = np.clip(H, 0, 20.0)

            n_flooded = int((H > 0.01).sum())
            cur_max = float(H.max()) if n_flooded else 0.0
            cur_total = float(H.sum()) * cell_area
            peak_max = max(peak_max, cur_max)
            peak_total = max(peak_total, cur_total)

            if step in out_indices or step == n_steps - 1:
                t_min = step * dt_min_target
                features = []
                if n_flooded > 50:
                    contour_depths = [0.05, 0.15, 0.30, 0.50]
                    for ci, cd in enumerate(contour_depths):
                        cm = (H >= cd) & (~mask)
                        if cm.sum() < 4:
                            continue
                        cm_u8 = cm.astype(np.uint8)
                        contours = find_contours(cm_u8, 0.5)
                        if not contours:
                            continue
                        contour = max(contours, key=len)
                        if len(contour) < 6:
                            continue
                        step2 = max(1, len(contour) // 50)
                        coords = []
                        for row_p, col_p in contour[::step2]:
                            rr = int(round(row_p)); cc = int(round(col_p))
                            if 0 <= rr < rows and 0 <= cc < cols and not mask[rr, cc]:
                                x_pt, y_pt = rt * (cc, rr)
                                lng_pt, lat_pt = to_wgs.transform(x_pt, y_pt)
                                z_pt = float(Z[rr, cc])
                                coords.append([round(lng_pt, 6), round(lat_pt, 6), round(z_pt, 2)])
                        if len(coords) >= 3:
                            coords.append(coords[0])
                            features.append({
                                "type": "Feature",
                                "properties": {
                                    "depth_m": cd,
                                    "level": ci + 1,
                                    "time_min": t_min,
                                },
                                "geometry": {"type": "Polygon", "coordinates": [coords]},
                            })


                grid_step = max(1, max(rows, cols) // 100)
                grid_depth = np.round(H[::grid_step, ::grid_step], 4).tolist()
                tin_vert_depths = [round(float(H[int(r), int(c)]), 4) for r, c in valid_rc]

                frames.append({
                    "step": step,
                    "time_min": t_min,
                    "time_hr": round(t_min / 60.0, 2),
                    "flooded_cells": n_flooded,
                    "flood_area_m2": round(cur_total, 1),
                    "max_depth_m": round(cur_max, 3),
                    "features": features,
                    "grid_depth": grid_depth,
                    "tin_vertex_depths": tin_vert_depths,
                })

        # Write final-frame TIN to GeoJSON files
        out_dir = Path(__file__).parent.parent.parent.parent / "data"
        out_dir.mkdir(parents=True, exist_ok=True)
        last_frame = frames[-1] if frames else None
        if last_frame and last_frame.get("tin_vertex_depths"):
            last_depths = last_frame["tin_vertex_depths"]
            tin_features_geo = []
            for orig_i, simp in valid_simps:
                cr = sum(valid_rc[vi][0] for vi in simp) / 3
                cc = sum(valid_rc[vi][1] for vi in simp) / 3
                ri, ci = int(round(cr)), int(round(cc))
                if 0 <= ri < rows and 0 <= ci < cols and mask[ri, ci]:
                    continue
                tri_coords = []
                for vi in simp:
                    tri_coords.append([round(float(tin_lng_arr[vi]), 6), round(float(tin_lat_arr[vi]), 6), round(float(tin_z_arr[vi]), 2)])
                tri_coords.append(tri_coords[0])
                td = [last_depths[vi] for vi in simp]
                te = [round(float(tin_z_arr[vi]), 2) for vi in simp]
                tin_features_geo.append({"type": "Feature", "properties": {"id": f"t_{orig_i}", "depth_m": round(sum(td)/3, 4), "vertex_depths": td, "vertex_elevs": te}, "geometry": {"type": "Polygon", "coordinates": [tri_coords]}})
            vert_features_geo = [{"type": "Feature", "properties": {"id": f"v_{vi}", "elevation_m": round(float(tin_z_arr[vi]), 2), "depth_m": last_depths[vi]}, "geometry": {"type": "Point", "coordinates": [round(float(tin_lng_arr[vi]), 6), round(float(tin_lat_arr[vi]), 6), round(float(tin_z_arr[vi]), 2)]}} for vi in range(len(tin_lng_arr))]
            (out_dir / "tin_triangles.geojson").write_text(_json.dumps({"type": "FeatureCollection", "features": tin_features_geo}, ensure_ascii=False), encoding="utf-8")
            (out_dir / "tin_vertices.geojson").write_text(_json.dumps({"type": "FeatureCollection", "features": vert_features_geo}, ensure_ascii=False), encoding="utf-8")
            for fi, fr in enumerate(frames):
                fd = fr.get("tin_vertex_depths", [])
                if not fd:
                    continue
                ftin = []
                for orig_i, simp in valid_simps:
                    cr = sum(valid_rc[vi][0] for vi in simp) / 3
                    cc = sum(valid_rc[vi][1] for vi in simp) / 3
                    ri, ci = int(round(cr)), int(round(cc))
                    if 0 <= ri < rows and 0 <= ci < cols and mask[ri, ci]:
                        continue
                    tc = [[round(float(tin_lng_arr[vi]), 6), round(float(tin_lat_arr[vi]), 6), round(float(tin_z_arr[vi]), 2)] for vi in simp]
                    tc.append(tc[0])
                    td2 = [fd[vi] for vi in simp]
                    te2 = [round(float(tin_z_arr[vi]), 2) for vi in simp]
                    ftin.append({"type": "Feature", "properties": {"id": f"t_{orig_i}", "depth_m": round(sum(td2)/3, 4), "vertex_depths": td2, "vertex_elevs": te2}, "geometry": {"type": "Polygon", "coordinates": [tc]}})
                (out_dir / f"tin_frame_{fi:03d}.geojson").write_text(_json.dumps({"type": "FeatureCollection", "features": ftin}, ensure_ascii=False), encoding="utf-8")

        tin_simplices = [[int(vi) for vi in simp] for _, simp in valid_simps]

        return {
            "simulation_type": "2D diffusive wave (LISFLOOD-FP style), central-difference fluxes, Manning friction",
            "manning_n": manning_n,
            "rainfall_mm": rainfall_mm,
            "rain_pattern": rain_pattern,
            "duration_hr": duration_hr,
            "time_step_min": dt_min_target,
            "total_steps": n_steps,
            "infiltration_mm_hr": infiltration_mm_hr,
            "grid_size": f"{cols}x{rows}",
            "cell_size_m": round((cell_x + cell_y) / 2, 1),
            "elevation_range_m": [round(elev_min, 2), round(elev_max, 2)],
            "bounds_wgs84": [[round(lng_min_wgs, 6), round(lat_min_wgs, 6)], [round(lng_max_wgs, 6), round(lat_max_wgs, 6)]],
            "n_frames": len(frames),
            "peak_max_depth_m": round(peak_max, 3),
            "peak_total_volume_m3": round(peak_total, 1),
            "cumulative_rainfall_mm": round(cum_rain_mm, 2),
            "grid_rows": len(np.arange(0, rows, grid_step)),
            "grid_cols": len(np.arange(0, cols, grid_step)),
            "grid_step": grid_step,
            "grid_terrain": np.round(Z[::grid_step, ::grid_step], 2).tolist(),
            "grid_nodata_mask": mask[::grid_step, ::grid_step].astype(int).tolist(),
            "tin_n_vertices": len(tin_lng_arr),
            "tin_n_triangles": len(tin_simplices),
            "tin_vertex_lng": tin_lng_arr.tolist(),
            "tin_vertex_lat": tin_lat_arr.tolist(),
            "tin_vertex_elev": tin_z_arr.tolist(),
            "tin_simplices": tin_simplices,
            "frames": frames,
            "dem_source": str(real_dem),
        }


TOOLS = [
    Tool(name="flood_assessment", description="Assess urban flooding risk for a given area", inputSchema={"type": "object", "properties": {"area_name": {"type": "string", "default": "demo_area"}, "rainfall_mm": {"type": "number", "default": 100}, "drainage_area_ha": {"type": "number", "default": 20}, "impervious_pct": {"type": "number", "default": 65}, "pipe_capacity_cms": {"type": "number", "default": 2}}, "required": []}),
    Tool(name="flood_inundation_map", description="Generate flood inundation polygon rings as GeoJSON", inputSchema={"type": "object", "properties": {"center_lng": {"type": "number", "default": 116.397}, "center_lat": {"type": "number", "default": 39.908}, "radius_m": {"type": "number", "default": 1000}, "max_depth_m": {"type": "number", "default": 0.5}}, "required": []}),
    Tool(name="hydrodynamic_2d_sim", description="2D kinematic-wave flood simulation with time series output, supports playback animation", inputSchema={"type": "object", "properties": {"lng_min": {"type": "number", "default": 0}, "lng_max": {"type": "number", "default": 0}, "lat_min": {"type": "number", "default": 0}, "lat_max": {"type": "number", "default": 0}, "rainfall_mm": {"type": "number", "default": 100}, "duration_hr": {"type": "number", "default": 24}, "time_step_min": {"type": "number", "default": 30}, "manning_n": {"type": "number", "default": 0.05}, "infiltration_mm_hr": {"type": "number", "default": 2}, "output_steps": {"type": "integer", "default": 12}}, "required": []}),
    Tool(name="flood_risk_zones", description="Classify area into flood risk zones", inputSchema={"type": "object", "properties": {"population_density": {"type": "number", "default": 5000}, "infrastructure_density": {"type": "number", "default": 0.3}}, "required": []}),
    Tool(name="drainage_assessment", description="Assess drainage pipe capacity using Manning formula", inputSchema={"type": "object", "properties": {"pipe_diameter_m": {"type": "number", "default": 0.8}, "pipe_slope": {"type": "number", "default": 0.003}, "manning_n": {"type": "number", "default": 0.013}, "design_flow_cms": {"type": "number", "default": 1.5}, "pipe_length_m": {"type": "number", "default": 500}}, "required": []}),
    Tool(name="flood_warning", description="Generate flood warning level with recommended actions", inputSchema={"type": "object", "properties": {"area_name": {"type": "string", "default": "demo_area"}, "current_rainfall_mm_hr": {"type": "number", "default": 60}, "forecast_rainfall_mm_hr": {"type": "number", "default": 80}, "soil_saturation_pct": {"type": "number", "default": 70}, "drainage_utilization_pct": {"type": "number", "default": 85}}, "required": []}),
]

HANDLERS = {
    "flood_assessment": flood_assessment,
    "flood_inundation_map": flood_inundation_map,
    "hydrodynamic_2d_sim": hydrodynamic_2d_sim,
    "flood_risk_zones": flood_risk_zones,
    "drainage_assessment": drainage_assessment,
    "flood_warning": flood_warning,
}

mcp_server = Server("mcp-flood")
sse = SseServerTransport("/messages/")
app = FastAPI(title="MCP Flood Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    handler = HANDLERS.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    try:
        result = await handler(**arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
    except Exception as e:
        logger.exception("tool_error", tool=name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


@app.get("/health")
async def health():
    return {"status": "healthy", "server": "mcp-flood", "tools": len(TOOLS)}


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    handler = HANDLERS.get(body.get("name"))
    if not handler:
        return {"error": f"Unknown tool: {body.get('name')}"}
    return await handler(**body.get("arguments", {}))


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=5006)


if __name__ == "__main__":
    main()
