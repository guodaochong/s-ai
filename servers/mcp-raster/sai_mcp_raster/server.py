from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

logger = structlog.get_logger(__name__)

DEM_DIR = Path(__file__).parent.parent.parent.parent / "data"
REAL_DEM = DEM_DIR / "LBH_DEM_v2_0.5m_EPSG4544.tif"
SYNTHETIC_DEM = DEM_DIR / "dem_beijing.npy"

SAMPLE_MAX = 2000


def _find_dem(dem_path: str = "") -> str:
    if dem_path and Path(dem_path).exists():
        return dem_path
    if REAL_DEM.exists():
        return str(REAL_DEM)
    return ""


def _sample_window(ds, max_px: int = SAMPLE_MAX):
    import rasterio.windows
    w, h = ds.width, ds.height
    if w <= max_px and h <= max_px:
        return rasterio.windows.Window(0, 0, w, h)
    rw = max_px / w
    rh = max_px / h
    r = min(rw, rh)
    nw, nh = int(w * r), int(h * r)
    ox = (w - nw) // 2
    oy = (h - nh) // 2
    return rasterio.windows.Window(ox, oy, nw, nh)


async def dem_analyze(
    dem_path: str = "",
    cell_size_m: float = 0.0,
    compute_slope: bool = True,
    compute_aspect: bool = True,
    compute_flowdir: bool = True,
) -> dict[str, Any]:
    import numpy as np

    path = _find_dem(dem_path)
    result: dict[str, Any] = {"dem_path": path or "none"}

    if not path:
        return {**result, "error": "No DEM file found. Upload a GeoTIFF DEM first."}

    try:
        import rasterio
    except ImportError:
        return {**result, "error": "rasterio not available"}

    with rasterio.open(path) as ds:
        win = _sample_window(ds)
        data = ds.read(1, window=win)
        nodata = ds.nodata if ds.nodata else -9999
        cell = abs(ds.transform[0])

        mask = data == nodata
        if mask.all():
            mask = np.isnan(data)
        valid = data[~mask]

        result["statistics"] = {
            "min_elevation_m": round(float(np.min(valid)), 2),
            "max_elevation_m": round(float(np.max(valid)), 2),
            "mean_elevation_m": round(float(np.mean(valid)), 2),
            "elevation_range_m": round(float(np.ptp(valid)), 2),
            "std_elevation_m": round(float(np.std(valid)), 2),
        }
        result["grid_info"] = {
            "full_width": ds.width, "full_height": ds.height,
            "sample_width": int(win.width), "sample_height": int(win.height),
            "cell_size_m": round(cell, 2), "crs": str(ds.crs),
            "bounds": [round(ds.bounds.left, 1), round(ds.bounds.bottom, 1),
                       round(ds.bounds.right, 1), round(ds.bounds.top, 1)],
        }

        if compute_slope or compute_aspect:
            fdata = data.astype(np.float64)
            fdata[mask] = np.nan
            dy, dx = np.gradient(fdata, cell, cell)
            slope_rad = np.arctan(np.sqrt(np.nan_to_num(dx) ** 2 + np.nan_to_num(dy) ** 2))
            slope_deg = np.degrees(slope_rad)
            slope_deg[mask] = 0
            vs = slope_deg[~mask]

            if compute_slope:
                bins = [0, 3, 5, 8, 15, 25, 45, 90]
                labels = ["0-3°", "3-5°", "5-8°", "8-15°", "15-25°", "25-45°", "45-90°"]
                hist, _ = np.histogram(vs, bins=bins)
                total = len(vs)
                result["slope"] = {
                    "min_deg": round(float(np.min(vs)), 2),
                    "max_deg": round(float(np.max(vs)), 2),
                    "mean_deg": round(float(np.mean(vs)), 2),
                    "std_deg": round(float(np.std(vs)), 2),
                    "histogram": [{"range": labels[i], "pct": round(float(hist[i] / total * 100), 1)} for i in range(len(labels))],
                }

            if compute_aspect:
                aspect_rad = np.arctan2(-np.nan_to_num(dy), np.nan_to_num(dx))
                aspect_deg = np.degrees(aspect_rad) % 360
                aspect_deg[mask] = -1
                va = aspect_deg[~mask]
                dir_names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
                dirs = {d: 0 for d in dir_names}
                for a in va:
                    idx = int((a + 22.5) / 45) % 8
                    dirs[dir_names[idx]] += 1
                dominant = max(dirs, key=dirs.get)
                total_a = len(va)
                result["aspect"] = {
                    "dominant": dominant,
                    "distribution": {k: round(v / total_a * 100, 1) for k, v in dirs.items()},
                }

            if compute_flowdir:
                fd = (np.arctan2(-np.nan_to_num(dy), np.nan_to_num(dx)) * 180 / np.pi) % 360
                fd[mask] = -1
                vf = fd[~mask]
                dir_names = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]
                dirs = {d: 0 for d in dir_names}
                for a in vf:
                    idx = int((a + 22.5) / 45) % 8
                    dirs[dir_names[idx]] += 1
                dominant = max(dirs, key=dirs.get)
                result["flow_direction"] = {
                    "dominant": dominant,
                    "convergence_points": int(np.sum(vs > 25) // 100),
                    "drainage_pattern": "dendritic" if np.std(vs) > 10 else "parallel",
                }

        if compute_slope:
            from skimage.measure import find_contours
            from pyproj import Transformer
            transformer = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)
            slope_classes = [
                {"label": "flat", "range": "0-5°", "min": 0, "max": 5, "color": "#44ff44"},
                {"label": "gentle", "range": "5-15°", "min": 5, "max": 15, "color": "#bbff00"},
                {"label": "moderate", "range": "15-25°", "min": 15, "max": 25, "color": "#ffcc00"},
                {"label": "steep", "range": "25-45°", "min": 25, "max": 45, "color": "#ff6600"},
                {"label": "very_steep", "range": "45-90°", "min": 45, "max": 90, "color": "#ff0000"},
            ]
            features = []
            win_obj = win
            for sc in slope_classes:
                class_mask = ((slope_deg >= sc["min"]) & (slope_deg < sc["max"])).astype(np.uint8)
                if not class_mask.any():
                    continue
                contours = find_contours(class_mask, 0.5)
                if not contours:
                    continue
                contour = max(contours, key=len)
                if len(contour) < 4:
                    continue
                step = max(1, len(contour) // 60)
                sampled = contour[::step]
                coords = []
                for r, c in sampled:
                    px = win_obj.col_off + c
                    py = win_obj.row_off + r
                    x, y = ds.xy(py, px)
                    lng, lat = transformer.transform(x, y)
                    coords.append([round(lng, 6), round(lat, 6)])
                if coords:
                    coords.append(coords[0])
                if len(coords) >= 4:
                    features.append({
                        "type": "Feature",
                        "properties": {"slope_class": sc["label"], "range": sc["range"], "color": sc["color"]},
                        "geometry": {"type": "Polygon", "coordinates": [coords]},
                    })
            if features:
                result["slope_geojson"] = {"type": "FeatureCollection", "features": features}

    return result


async def flow_accumulation(
    dem_path: str = "",
    threshold_cells: int = 100,
) -> dict[str, Any]:
    import numpy as np

    path = _find_dem(dem_path)
    if not path:
        return {"error": "No DEM file found"}

    import rasterio
    from rasterio.enums import Resampling
    from pyproj import Transformer

    with rasterio.open(path) as ds:
        w, h = ds.width, ds.height
        import rasterio.windows
        from rasterio.transform import Affine
        max_px = 4000
        if w <= max_px and h <= max_px:
            data = ds.read(1)
            win = rasterio.windows.Window(0, 0, w, h)
            rt = ds.transform
        else:
            import rasterio.windows as rw_mod
            rw, rh = max_px / w, max_px / h
            r = min(rw, rh)
            nw, nh = max(int(w * r), 2), max(int(h * r), 2)
            data = ds.read(1, out_shape=(nh, nw), resampling=Resampling.average)
            win = rw_mod.Window(0, 0, nw, nh)
            rt = ds.transform * Affine.scale(w / nw, h / nh)
        nodata = ds.nodata if ds.nodata else -9999
        cell = abs(rt[0])
        mask = data == nodata
        fdata = data.astype(np.float64)
        if np.any(~mask):
            fdata[mask] = np.nanmin(fdata[~mask])
        else:
            fdata[:] = 0

        rows, cols = fdata.shape
        filled = fdata.copy()
        for _ in range(3):
            padded = np.pad(filled, 1, mode='edge')
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    if dr == 0 and dc == 0:
                        continue
                    nb = padded[1+dr:1+dr+rows, 1+dc:1+dc+cols]
                    filled = np.where((~mask) & (filled < nb), nb, filled)

        dr8 = np.array([0, 1, 1, 1, 0, -1, -1, -1], dtype=np.intp)
        dc8 = np.array([1, 1, 0, -1, -1, -1, 0, 1], dtype=np.intp)
        dist8 = np.array([1.0, np.sqrt(2), 1.0, np.sqrt(2), 1.0, np.sqrt(2), 1.0, np.sqrt(2)])

        fdir = np.zeros((rows, cols), dtype=np.int8)
        fdir[mask] = -1

        padded = np.pad(filled, 1, mode='constant', constant_values=np.inf)
        max_slope = np.full((rows, cols), -np.inf)

        for d in range(8):
            nb = padded[1+dr8[d]:1+dr8[d]+rows, 1+dc8[d]:1+dc8[d]+cols]
            slope = (filled - nb) / (dist8[d] * cell)
            better = (~mask) & (slope > max_slope)
            fdir[better] = d
            max_slope[better] = slope[better]

        flats = (~mask) & (max_slope <= 0) & (fdir >= 0)
        if np.any(flats):
            padded_f = np.pad(filled, 1, mode='constant', constant_values=np.inf)
            for d in range(8):
                nb_elev = padded_f[1+dr8[d]:1+dr8[d]+rows, 1+dc8[d]:1+dc8[d]+cols]
                toward_lower = flats & (nb_elev < filled)
                fdir[toward_lower] = d

        # Vectorized flow accumulation via sorted traversal
        acc = np.ones((rows, cols), dtype=np.float64)
        acc[mask] = 0

        order = np.argsort(filled.ravel())[::-1]
        r_all = order // cols
        c_all = order % cols
        d_all = fdir[r_all, c_all]
        valid_mask = ~mask[r_all, c_all] & (d_all >= 0)
        nr_all = r_all + dr8[d_all]
        nc_all = c_all + dc8[d_all]
        in_bounds = (nr_all >= 0) & (nr_all < rows) & (nc_all >= 0) & (nc_all < cols) & valid_mask
        nr_safe = np.clip(nr_all, 0, rows - 1)
        nc_safe = np.clip(nc_all, 0, cols - 1)
        ok = np.where(in_bounds)[0]

        for i in ok:
            acc[nr_safe[i], nc_safe[i]] += acc[r_all[i], c_all[i]]

        acc[mask] = 0
        max_acc = float(np.max(acc[~mask])) if np.any(~mask) else 1
        threshold = max(threshold_cells, max_acc * 0.02)
        stream_mask = acc > threshold

        # Strahler ordering (ascending accumulation)
        strahler = np.zeros((rows, cols), dtype=np.int8)
        asc_order = np.argsort(acc.ravel())
        stream_flat = stream_mask.ravel()
        for idx in asc_order:
            if not stream_flat[idx]:
                continue
            r, c = divmod(int(idx), cols)
            ups = []
            for ud in range(8):
                ur, uc = r + int(dr8[ud]), c + int(dc8[ud])
                if 0 <= ur < rows and 0 <= uc < cols:
                    if fdir[ur, uc] == (ud + 4) % 8 and strahler[ur, uc] > 0:
                        ups.append(int(strahler[ur, uc]))
            if not ups:
                strahler[r, c] = 1
            else:
                mx = max(ups)
                strahler[r, c] = mx + 1 if sum(1 for o in ups if o == mx) >= 2 else mx

        transformer = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)

        stream_lines = []
        stream_id = 0
        visited = np.zeros((rows, cols), dtype=bool)
        flat_acc = acc.ravel()
        order_by_acc = np.argsort(flat_acc)[::-1]

        for idx in order_by_acc:
            if flat_acc[idx] <= threshold:
                break
            if visited.flat[idx]:
                continue
            r, c = divmod(int(idx), cols)
            # Walk upstream to find source
            src_r, src_c = r, c
            for _ in range(rows + cols):
                best_up = -1
                best_up_acc = -1
                for ud in range(8):
                    ur, uc = src_r + int(dr8[ud]), src_c + int(dc8[ud])
                    if 0 <= ur < rows and 0 <= uc < cols and not visited[ur, uc]:
                        if fdir[ur, uc] == (ud + 4) % 8 and stream_mask[ur, uc]:
                            if acc[ur, uc] > best_up_acc:
                                best_up_acc = acc[ur, uc]
                                best_up = ud
                if best_up < 0:
                    break
                src_r += int(dr8[best_up])
                src_c += int(dc8[best_up])

            line_coords = []
            ms = 0
            cr, cc = src_r, src_c
            while 0 <= cr < rows and 0 <= cc < cols and stream_mask[cr, cc] and not visited[cr, cc]:
                visited[cr, cc] = True
                x, y = rt * (win.col_off + cc + 0.5, win.row_off + cr + 0.5)
                lng, lat = transformer.transform(x, y)
                line_coords.append([round(lng, 6), round(lat, 6)])
                ms = max(ms, int(strahler[cr, cc]))
                d = fdir[cr, cc]
                if d < 0:
                    break
                cr += int(dr8[d])
                cc += int(dc8[d])

            if len(line_coords) >= 6:
                stream_id += 1
                n = len(line_coords)
                step = max(1, n // 80)
                sampled = line_coords[::step]
                if sampled[-1] != line_coords[-1]:
                    sampled.append(line_coords[-1])
                er = min(cr, rows - 1)
                ec = min(cc, cols - 1)
                max_acc_in_stream = max(acc[src_r, src_c], acc[r, c])
                stream_lines.append({
                    "id": f"stream_{stream_id}",
                    "order": max(ms, 1),
                    "length_m": round(n * cell, 1),
                    "source_elev_m": round(float(fdata[src_r, src_c]), 1),
                    "outlet_elev_m": round(float(fdata[er, ec]), 1),
                    "accumulation": int(max_acc_in_stream),
                    "n_pixels": n,
                    "coords": sampled,
                })
            if stream_id >= 50:
                break

        stream_lines.sort(key=lambda s: s["length_m"], reverse=True)
        stream_lines = stream_lines[:40]

        order_colors = {1: "#88bbff", 2: "#4499ff", 3: "#00ccff", 4: "#00ffcc", 5: "#00ff66", 6: "#ffcc00"}
        geo_features = []
        for s in stream_lines:
            pts = s.pop("coords")
            if len(pts) < 2:
                continue
            geo_features.append({
                "type": "Feature",
                "properties": {
                    "id": s["id"], "order": s["order"], "length_m": s["length_m"],
                    "source_elev": s["source_elev_m"], "outlet_elev": s["outlet_elev_m"],
                    "accumulation": s["accumulation"],
                    "color": order_colors.get(s["order"], "#00d4ff"),
                    "weight": min(1 + s["order"], 6),
                },
                "geometry": {"type": "LineString", "coordinates": pts},
            })

        stream_geojson = {"type": "FeatureCollection", "features": geo_features}
        total_len = sum(s["length_m"] for s in stream_lines)
        total_area_m2 = rows * cols * cell * cell
        ms_val = max((s["order"] for s in stream_lines), default=0)
        return {
            "dem_path": path, "threshold_cells": threshold_cells,
            "n_streams": len(stream_lines), "streams": stream_lines[:15],
            "max_flow_accumulation": int(max_acc),
            "max_strahler_order": ms_val,
            "drainage_density_km_per_km2": round(total_len / 1000 / (total_area_m2 / 1e6), 2) if total_area_m2 > 0 else 0,
            "total_stream_length_km": round(total_len / 1000, 2),
            "sample_grid": f"{cols}x{rows}",
            "cell_size_m": round(cell, 2),
            "coverage_km2": round(total_area_m2 / 1e6, 2),
            "algorithm": "D8_sorted_traversal",
            "stream_geojson": stream_geojson,
        }


async def watershed_delineate(
    outlet_x: float = 0,
    outlet_y: float = 0,
    snap_distance_m: float = 50.0,
    outlet_lng: float = 0,
    outlet_lat: float = 0,
) -> dict[str, Any]:
    import numpy as np

    path = _find_dem()
    if not path:
        return {"error": "No DEM file found"}

    import rasterio
    from rasterio.transform import rowcol

    with rasterio.open(path) as ds:
        bounds = ds.bounds
        cx = (bounds.left + bounds.right) / 2
        cy = (bounds.top + bounds.bottom) / 2

        if outlet_x == 0 and outlet_y == 0:
            outlet_x, outlet_y = cx, cy

        row, col = rowcol(ds.transform, outlet_x, outlet_y)
        row = max(0, min(row, ds.height - 1))
        col = max(0, min(col, ds.width - 1))

        half = min(500, ds.width // 4, ds.height // 4)
        import rasterio.windows
        win = rasterio.windows.Window(max(0, col - half), max(0, row - half), half * 2, half * 2)
        data = ds.read(1, window=win)
        nodata = ds.nodata if ds.nodata else -9999
        cell = abs(ds.transform[0])

        mask = data == nodata
        fdata = data.astype(np.float64)
        fdata[mask] = np.inf

        dy, dx = np.gradient(fdata, cell, cell)
        fd = np.arctan2(-dx, dy)
        fd[mask] = 0

        wr, wc = min(half, data.shape[0] - 1), min(half, data.shape[1] - 1)
        visited = np.zeros_like(data, dtype=bool)
        stack = [(wr, wc)]
        visited[wr, wc] = True
        count = 0
        max_cells = half * half * 4
        while stack and count < max_cells:
            r, c = stack.pop()
            count += 1
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < data.shape[0] and 0 <= nc < data.shape[1] and not visited[nr, nc] and not mask[nr, nc]:
                        a = fd[nr, nc]
                        tr, tc = nr + int(round(-math.sin(a))), nc + int(round(math.cos(a)))
                        if tr == r and tc == c:
                            visited[nr, nc] = True
                            stack.append((nr, nc))

        ws_pixels = int(np.sum(visited))
        area_km2 = ws_pixels * cell * cell / 1e6

        coords = []
        step = max(1, data.shape[1] // 30)
        top_row = np.argmax(visited, axis=0)
        for c in range(0, data.shape[1], step):
            if visited[top_row[c], c]:
                px = win.col_off + c
                py = win.row_off + top_row[c]
                x, y = ds.xy(py, px)
                coords.append([round(x, 1), round(y, 1)])
        if coords:
            coords.append(coords[0])

        geojson = {"type": "Polygon", "coordinates": [coords]} if len(coords) >= 4 else None

        return {
            "outlet": [round(outlet_x, 1), round(outlet_y, 1)],
            "snap_distance_m": snap_distance_m,
            "watershed_area_km2": round(area_km2, 3),
            "watershed_cells": ws_pixels,
            "cell_size_m": round(cell, 2),
            "perimeter_km": round(math.sqrt(area_km2) * 4, 2),
            "boundary_geojson": geojson,
            "crs": str(ds.crs),
            "note": "Coordinates in projected CRS (meters), not WGS84" if geojson else "Watershed too small to extract boundary",
        }


async def terrain_profile(
    start_x: float = 0,
    start_y: float = 0,
    end_x: float = 0,
    end_y: float = 0,
    n_points: int = 30,
    start_lng: float = 0,
    start_lat: float = 0,
    end_lng: float = 0,
    end_lat: float = 0,
) -> dict[str, Any]:
    import numpy as np
    import math

    path = _find_dem()
    if not path:
        return {"error": "No DEM file found"}

    import rasterio
    from pyproj import Transformer

    with rasterio.open(path) as ds:
        t_crs = ds.crs
        to_proj = Transformer.from_crs("EPSG:4326", t_crs, always_xy=True)
        to_wgs84 = Transformer.from_crs(t_crs, "EPSG:4326", always_xy=True)

        has_lng = start_lng != 0 or end_lng != 0
        if has_lng:
            s1 = start_lng if start_lng != 0 else start_x
            s2 = start_lat if start_lat != 0 else start_y
            e1 = end_lng if end_lng != 0 else end_x
            e2 = end_lat if end_lat != 0 else end_y
            s_lng, s_lat = s1, s2
            e_lng, e_lat = e1, e2
        elif start_x != 0 or start_y != 0:
            s_lng, s_lat = start_x, start_y
            e_lng, e_lat = end_x if end_x != 0 else start_x, end_y if end_y != 0 else start_y
        else:
            s_lng, s_lat = 104.86, 33.23
            e_lng, e_lat = 104.89, 33.25

        sx, sy = to_proj.transform(s_lng, s_lat)
        ex, ey = to_proj.transform(e_lng, e_lat)

        R = 6371000
        dlat = math.radians(e_lat - s_lat)
        dlon = math.radians(e_lng - s_lng)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(s_lat)) * math.cos(math.radians(e_lat)) * math.sin(dlon/2)**2
        total_dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        s_row, s_col = ds.index(sx, sy)
        e_row, e_col = ds.index(ex, ey)

        half = 500
        min_r = max(0, min(s_row, e_row) - half)
        max_r = min(ds.height, max(s_row, e_row) + half)
        min_c = max(0, min(s_col, e_col) - half)
        max_c = min(ds.width, max(s_col, e_col) + half)

        import rasterio.windows
        win = rasterio.windows.Window(min_c, min_r, max_c - min_c, max_r - min_r)
        data = ds.read(1, window=win)
        nodata = ds.nodata if ds.nodata else -9999

        profile = []
        for i in range(n_points):
            t = i / max(1, n_points - 1)
            px = sx + t * (ex - sx)
            py = sy + t * (ey - sy)
            r, c = ds.index(px, py)
            r -= win.row_off
            c -= win.col_off
            if 0 <= r < data.shape[0] and 0 <= c < data.shape[1]:
                elev = float(data[r, c])
                if elev == nodata:
                    elev = None
            else:
                elev = None
            lng_out, lat_out = to_wgs84.transform(px, py)
            profile.append({
                "distance_m": round(t * total_dist, 1),
                "elevation_m": round(elev, 2) if elev is not None else None,
                "lng": round(lng_out, 6),
                "lat": round(lat_out, 6),
            })

        valid_elevs = [p["elevation_m"] for p in profile if p["elevation_m"] is not None]
        return {
            "start": [round(s_lng, 6), round(s_lat, 6)],
            "end": [round(e_lng, 6), round(e_lat, 6)],
            "total_distance_m": round(total_dist, 1),
            "max_elevation_m": round(max(valid_elevs), 2) if valid_elevs else None,
            "min_elevation_m": round(min(valid_elevs), 2) if valid_elevs else None,
            "profile": profile,
            "crs": str(ds.crs),
            "dem_source": path,
        }


async def dem_render(
    dem_path: str = "",
    contour_interval: float = 20.0,
) -> dict[str, Any]:
    import numpy as np

    path = _find_dem(dem_path)
    if not path:
        return {"error": "No DEM file found"}

    import rasterio
    from rasterio.enums import Resampling
    from pyproj import Transformer
    import rasterio.windows

    with rasterio.open(path) as ds:
        w, h = ds.width, ds.height
        from rasterio.transform import Affine
        max_px = 2000
        if w <= max_px and h <= max_px:
            data = ds.read(1)
            win = rasterio.windows.Window(0, 0, w, h)
            rt = ds.transform
        else:
            rw, rh = max_px / w, max_px / h
            r = min(rw, rh)
            nw, nh = max(int(w * r), 2), max(int(h * r), 2)
            data = ds.read(1, out_shape=(nh, nw), resampling=Resampling.average)
            win = rasterio.windows.Window(0, 0, nw, nh)
            rt = ds.transform * Affine.scale(w / nw, h / nh)
        nodata = ds.nodata if ds.nodata else -9999
        cell = abs(rt[0])
        mask = data == nodata
        fdata = data.astype(np.float64)
        if np.any(~mask):
            fdata[mask] = np.nanmin(fdata[~mask])

        rows, cols = fdata.shape
        transformer = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)

        # Hillshade
        az_rad = 315 * np.pi / 180
        alt_rad = 45 * np.pi / 180
        dy, dx = np.gradient(fdata, cell, cell)
        slope = np.arctan(np.sqrt(dx*dx + dy*dy))
        aspect = np.arctan2(-dy, dx)
        hillshade = np.cos(alt_rad) * np.cos(slope) + np.sin(alt_rad) * np.sin(slope) * np.cos(az_rad - aspect)
        hillshade = np.clip(hillshade * 255, 0, 255).astype(np.uint8)
        hillshade[mask] = 0

        # Contour lines as GeoJSON
        min_elev = float(np.floor(np.nanmin(fdata[~mask]) / contour_interval) * contour_interval) if np.any(~mask) else 0
        max_elev = float(np.ceil(np.nanmax(fdata[~mask]) / contour_interval) * contour_interval) if np.any(~mask) else 100
        levels = np.arange(min_elev, max_elev + contour_interval, contour_interval)

        try:
            from skimage.measure import find_contours as _fc
        except (ImportError, ValueError):
            _fc = None

        contour_features = []
        c_id = 0
        if _fc:
            for level in levels:
                for c_arr in _fc(fdata, level):
                    if len(c_arr) < 4:
                        continue
                    coords = []
                    step = max(1, len(c_arr) // 80)
                    for i in range(0, len(c_arr), step):
                        cr_v, cc_v = c_arr[i]
                        cr_i, cc_i = int(round(cr_v)), int(round(cc_v))
                        if 0 <= cr_i < rows and 0 <= cc_i < cols:
                            x, y = rt * (win.col_off + cc_i + 0.5, win.row_off + cr_i + 0.5)
                            lng, lat = transformer.transform(x, y)
                            coords.append([round(lng, 6), round(lat, 6)])
                    if len(coords) >= 3:
                        coords.append(coords[0])
                        c_id += 1
                        contour_features.append({
                            "type": "Feature",
                            "properties": {"id": f"c_{c_id}", "elevation": round(float(level), 1)},
                            "geometry": {"type": "LineString", "coordinates": coords},
                        })

        # Hillshade image bounds
        corners = [(0, 0), (0, cols), (rows, 0), (rows, cols)]
        lngs_lats = []
        for cr, cc in corners:
            x, y = rt * (win.col_off + cc + 0.5, win.row_off + cr + 0.5)
            lng, lat = transformer.transform(x, y)
            lngs_lats.append((lng, lat))
        bounds = [[min(l[1] for l in lngs_lats), min(l[0] for l in lngs_lats)],
                   [max(l[1] for l in lngs_lats), max(l[0] for l in lngs_lats)]]

        # Encode hillshade as PNG base64
        import io, base64
        from PIL import Image
        img = Image.fromarray(hillshade, mode='L')
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()

        contour_geojson = {"type": "FeatureCollection", "features": contour_features}
        return {
            "dem_path": path,
            "contour_interval_m": contour_interval,
            "n_contours": len(contour_features),
            "elevation_range": [round(min_elev, 1), round(max_elev, 1)],
            "hillshade_bounds": bounds,
            "hillshade_image": f"data:image/png;base64,{b64}",
            "contour_geojson": contour_geojson,
            "grid_size": f"{cols}x{rows}",
            "cell_size_m": round(cell, 2),
        }


async def point_query(
    lng: float = 0,
    lat: float = 0,
    search_radius_m: float = 500.0,
) -> dict[str, Any]:
    import math
    import numpy as np
    import rasterio
    from pyproj import Transformer

    path = _find_dem()
    if not path:
        return {"error": "No DEM file found"}

    with rasterio.open(path) as ds:
        to_proj = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
        x, y = to_proj.transform(lng, lat)
        row, col = ds.index(x, y)
        if not (0 <= row < ds.height and 0 <= col < ds.width):
            return {"lng": lng, "lat": lat, "error": "Point outside DEM bounds"}

        cell = abs(ds.transform[0])
        win_r = max(1, int(search_radius_m / cell))
        r0, r1 = max(0, row - win_r), min(ds.height, row + win_r + 1)
        c0, c1 = max(0, col - win_r), min(ds.width, col + win_r + 1)
        from rasterio.windows import Window
        win = Window(c0, r0, c1 - c0, r1 - r0)
        data = ds.read(1, window=win).astype(np.float32)
        nd = ds.nodata if ds.nodata is not None else -9999
        mask = data == nd
        if mask.all():
            return {"lng": lng, "lat": lat, "error": "All nodata in search window"}
        if mask.any():
            data[mask] = float(np.mean(data[~mask]))

        elev = float(data[row - r0, col - c0])

        gy, gx = np.gradient(data, cell)
        local_r = row - r0
        local_c = col - c0
        slope_rad = np.arctan(np.sqrt(gx[local_r, local_c] ** 2 + gy[local_r, local_c] ** 2))
        slope_deg = float(np.degrees(slope_rad))
        if abs(gx[local_r, local_c]) < 1e-9 and abs(gy[local_r, local_c]) < 1e-9:
            aspect_deg = -1.0
        else:
            aspect_rad = np.arctan2(-gy[local_r, local_c], gx[local_r, local_c])
            aspect_deg = float((np.degrees(aspect_rad) + 360) % 360)
        aspect_label = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((aspect_deg + 22.5) / 45) % 8] if aspect_deg >= 0 else "Flat"

        curvature = float(gx[local_r, local_c] ** 2 + gy[local_r, local_c] ** 2)

        curv_plan = -((data[local_r, min(local_c + 1, data.shape[1] - 1)] - 2 * elev +
                       data[local_r, max(local_c - 1, 0)]) / (cell ** 2) +
                      (data[min(local_r + 1, data.shape[0] - 1), local_c] - 2 * elev +
                       data[max(local_r - 1, 0), local_c]) / (cell ** 2))
        TPI = elev - float(np.mean(data))
        TRI = float(np.std(data))

        return {
            "lng": round(lng, 6),
            "lat": round(lat, 6),
            "elevation_m": round(elev, 2),
            "slope_deg": round(slope_deg, 2),
            "slope_pct": round(math.tan(slope_rad) * 100, 1),
            "aspect_deg": round(aspect_deg, 1) if aspect_deg >= 0 else None,
            "aspect_label": aspect_label,
            "curvature_plan": round(curv_plan, 6),
            "TPI": round(TPI, 2),
            "TRI": round(TRI, 2),
            "neighborhood_window_m": round(2 * win_r * cell, 1),
            "dem_source": path,
            "spatial_classification": _classify_terrain(slope_deg, TPI, TRI, curv_plan),
        }


def _classify_terrain(slope_deg: float, tpi: float, tri: float, curv: float) -> str:
    if slope_deg < 2:
        if abs(tpi) < 2 and abs(curv) < 0.001:
            return "平原/平坦"
        if tpi > 5:
            return "山顶/高地"
        if tpi < -5:
            return "洼地/谷底"
        return "微起伏平地"
    if slope_deg < 8:
        if tpi > 3:
            return "山脊"
        if tpi < -3:
            return "山谷"
        return "缓坡"
    if slope_deg < 20:
        return "斜坡"
    if slope_deg < 35:
        return "陡坡"
    return "峭壁/悬崖"


async def tin_generate(
    lng_min: float = 0,
    lng_max: float = 0,
    lat_min: float = 0,
    lat_max: float = 0,
    max_points: int = 1500,
    refine_steep: bool = True,
    spacing_m: float = 0,
) -> dict[str, Any]:
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from scipy.spatial import Delaunay

    path = _find_dem()
    if not path:
        return {"error": "No DEM file found"}

    with rasterio.open(path) as ds:
        to_proj = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
        if lng_min == 0 and lng_max == 0:
            bl = ds.bounds
            to_wgs = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)
            lng_min, lat_min = to_wgs.transform(bl.left, bl.bottom)
            lng_max, lat_max = to_wgs.transform(bl.right, bl.top)
            margin = 0.05
            dl = (lng_max - lng_min) * margin
            dt = (lat_max - lat_min) * margin
            lng_min += dl; lng_max -= dl; lat_min += dt; lat_max -= dt

        x0, y0 = to_proj.transform(lng_min, lat_min)
        x1, y1 = to_proj.transform(lng_max, lat_max)
        col0, row1 = ds.index(x0, y1)
        col1, row0 = ds.index(x1, y0)
        col0, col1 = sorted([max(0, col0), min(ds.width - 1, col1)])
        row0, row1 = sorted([max(0, row0), min(ds.height - 1, row1)])

        cell_size_m = abs(ds.transform[0])
        if spacing_m > 0:
            step_r = max(1, int(spacing_m / cell_size_m))
            n_pts = ((col1 - col0 + 1) // step_r) * ((row1 - row0 + 1) // step_r)
            if n_pts > 100000:
                scale = int(np.ceil(np.sqrt(n_pts / 100000)))
                step_r *= scale
        else:
            step_r = max(1, int(np.sqrt((col1 - col0 + 1) * (row1 - row0 + 1) / max_points)))

        from rasterio.windows import Window
        win = Window(col0, row0, col1 - col0 + 1, row1 - row0 + 1)
        data = ds.read(1, window=win)
        nd = ds.nodata if ds.nodata is not None else -9999
        mask = data == nd
        if mask.all():
            return {"error": "All nodata in area"}
        data = data.astype(np.float64)

        if spacing_m > 0:
            sample_rows_arr = np.arange(0, data.shape[0], step_r)
            sample_cols_arr = np.arange(0, data.shape[1], step_r)
            rr, cc = np.meshgrid(sample_rows_arr, sample_cols_arr, indexing='ij')
            sample_rows = rr.ravel()
            sample_cols = cc.ravel()
        elif refine_steep:
            data_safe = data.copy()
            data_safe[mask] = np.nan
            gy, gx = np.gradient(np.nan_to_num(data_safe, nan=float(np.nanmean(data_safe))), abs(ds.transform[0]))
            slope = np.sqrt(gx ** 2 + gy ** 2)
            weights = 1.0 + slope * 5
            sub_step = step_r
            sample_rows, sample_cols = np.where((weights > 0) & (~mask))
            if len(sample_rows) > max_points * 3:
                prob = (weights[sample_rows, sample_cols] / weights[sample_rows, sample_cols].sum())
                idx = np.random.choice(len(sample_rows), size=max_points, replace=False, p=prob)
                sample_rows = sample_rows[idx]
                sample_cols = sample_cols[idx]
        else:
            sample_rows = np.arange(0, data.shape[0], step_r).repeat(len(np.arange(0, data.shape[1], step_r)))
            sample_cols = np.tile(np.arange(0, data.shape[1], step_r), len(np.arange(0, data.shape[0], step_r)))

        rt = ds.window_transform(win)
        to_wgs = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)
        points_xy = []
        elevations = []
        for r, c in zip(sample_rows, sample_cols):
            if mask.any() and 0 <= r < mask.shape[0] and 0 <= c < mask.shape[1] and mask[r, c]:
                continue
            x, y = rt * (c + 0.5, r + 0.5)
            lng, lat = to_wgs.transform(x, y)
            points_xy.append([lng, lat])
            elevations.append(float(data[r, c]))

        if len(points_xy) < 4:
            return {"error": "Not enough valid points for TIN"}

        pts = np.array(points_xy)
        elevs = np.array(elevations)
        tri = Delaunay(pts)
        triangles = tri.simplices
        valid = []
        for i, simp in enumerate(triangles):
            coords = pts[simp]
            el_vals = elevs[simp]
            mean_elev = float(np.mean(el_vals))
            valid.append({
                "type": "Feature",
                "properties": {
                    "id": f"t_{i}",
                    "elevation_m": round(mean_elev, 2),
                    "min_elev": round(float(np.min(el_vals)), 2),
                    "max_elev": round(float(np.max(el_vals)), 2),
                    "area_deg2": round(float(0.5 * abs(
                        (coords[1, 0] - coords[0, 0]) * (coords[2, 1] - coords[0, 1]) -
                        (coords[2, 0] - coords[0, 0]) * (coords[1, 1] - coords[0, 1])
                    )), 8),
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [round(float(coords[0, 0]), 6), round(float(coords[0, 1]), 6), round(float(el_vals[0]), 2)],
                        [round(float(coords[1, 0]), 6), round(float(coords[1, 1]), 6), round(float(el_vals[1]), 2)],
                        [round(float(coords[2, 0]), 6), round(float(coords[2, 1]), 6), round(float(el_vals[2]), 2)],
                        [round(float(coords[0, 0]), 6), round(float(coords[0, 1]), 6), round(float(el_vals[0]), 2)],
                    ]],
                },
            })

        elev_min = float(np.min(elevs))
        elev_max = float(np.max(elevs))

        vertex_features = []
        for vi in range(len(points_xy)):
            vertex_features.append({
                "type": "Feature",
                "properties": {"id": f"v_{vi}", "elevation_m": round(float(elevs[vi]), 2)},
                "geometry": {"type": "Point", "coordinates": [round(float(pts[vi, 0]), 6), round(float(pts[vi, 1]), 6), round(float(elevs[vi]), 2)]},
            })

        tin_fc = {"type": "FeatureCollection", "features": valid}
        vert_fc = {"type": "FeatureCollection", "features": vertex_features}
        import json
        out_dir = Path(__file__).parent.parent.parent.parent / "data"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "tin_triangles.geojson").write_text(json.dumps(tin_fc, ensure_ascii=False), encoding="utf-8")
        (out_dir / "tin_vertices.geojson").write_text(json.dumps(vert_fc, ensure_ascii=False), encoding="utf-8")

        return {
            "n_points": len(points_xy),
            "n_triangles": len(valid),
            "elevation_range_m": [round(elev_min, 2), round(elev_max, 2)],
            "mean_elev_m": round(float(np.mean(elevs)), 2),
            "tin_geojson": tin_fc,
            "vertices_geojson": vert_fc,
            "bounds_wgs84": [
                [round(lng_min, 6), round(lat_min, 6)],
                [round(lng_max, 6), round(lat_max, 6)],
            ],
            "dem_source": path,
            "refinement": "slope-adaptive" if refine_steep else "uniform",
            "spacing_m": spacing_m if spacing_m > 0 else round(cell_size_m * step_r, 1),
        }


async def quadtree_subdivide(
    lng_min: float = 0,
    lng_max: float = 0,
    lat_min: float = 0,
    lat_max: float = 0,
    max_depth: int = 4,
    variance_threshold: float = 50.0,
) -> dict[str, Any]:
    import numpy as np
    import rasterio
    from pyproj import Transformer

    path = _find_dem()
    if not path:
        return {"error": "No DEM file found"}

    with rasterio.open(path) as ds:
        to_proj = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
        to_wgs = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)

        if lng_min == 0 and lng_max == 0:
            bl = ds.bounds
            lng_min, lat_min = to_wgs.transform(bl.left, bl.bottom)
            lng_max, lat_max = to_wgs.transform(bl.right, bl.top)
            m = 0.1
            dl = (lng_max - lng_min) * m
            dt = (lat_max - lat_min) * m
            lng_min += dl; lng_max -= dl; lat_min += dt; lat_max -= dt

        x0, y0 = to_proj.transform(lng_min, lat_min)
        x1, y1 = to_proj.transform(lng_max, lat_max)
        from rasterio.windows import Window
        col0, row1 = ds.index(x0, y1)
        col1, row0 = ds.index(x1, y0)
        col0 = max(0, col0); row0 = max(0, row0)
        col1 = min(ds.width - 1, col1); row1 = min(ds.height - 1, row1)
        full_win = Window(col0, row0, col1 - col0 + 1, row1 - row0 + 1)
        data = ds.read(1, window=full_win).astype(np.float64)
        nd = ds.nodata if ds.nodata is not None else -9999
        mask = data == nd
        if mask.any():
            data[mask] = float(np.mean(data[~mask]))
        rt = ds.window_transform(full_win)
        rows, cols = data.shape

        def subdivide(c0, r0, c1, r1, depth, cells):
            block = data[r0:r1 + 1, c0:c1 + 1]
            if block.size < 4:
                return
            v = float(np.var(block))
            if depth >= max_depth or v < variance_threshold:
                xa, ya = rt * (c0, r0)
                xb, yb = rt * (c1 + 1, r0)
                xc, yc = rt * (c1 + 1, r1 + 1)
                xd, yd = rt * (c0, r1 + 1)
                la, la_ = to_wgs.transform(xa, ya)
                lb, lb_ = to_wgs.transform(xb, yb)
                lc, lc_ = to_wgs.transform(xc, yc)
                ld, ld_ = to_wgs.transform(xd, yd)
                cells.append({
                    "type": "Feature",
                    "properties": {
                        "depth": depth,
                        "variance": round(v, 2),
                        "mean_elev": round(float(np.mean(block)), 2),
                        "area_deg2": round(abs((lb[0] - la[0]) * (ld[1] - la[1])), 8),
                    },
                    "geometry": {"type": "Polygon", "coordinates": [[
                        [round(la[0], 6), round(la[1], 6)],
                        [round(lb[0], 6), round(lb[1], 6)],
                        [round(lc[0], 6), round(lc[1], 6)],
                        [round(ld[0], 6), round(ld[1], 6)],
                        [round(la[0], 6), round(la[1], 6)],
                    ]]},
                })
                return
            cm = (c0 + c1) // 2
            rm = (r0 + r1) // 2
            subdivide(c0, r0, cm, rm, depth + 1, cells)
            subdivide(cm + 1, r0, c1, rm, depth + 1, cells)
            subdivide(c0, rm + 1, cm, r1, depth + 1, cells)
            subdivide(cm + 1, rm + 1, c1, r1, depth + 1, cells)

        cells = []
        subdivide(0, 0, cols - 1, rows - 1, 0, cells)

        depth_counts = {}
        for c in cells:
            d = c["properties"]["depth"]
            depth_counts[d] = depth_counts.get(d, 0) + 1

        return {
            "n_cells": len(cells),
            "max_depth_reached": max((c["properties"]["depth"] for c in cells), default=0),
            "depth_distribution": depth_counts,
            "quadtree_geojson": {"type": "FeatureCollection", "features": cells},
            "bounds_wgs84": [
                [round(lng_min, 6), round(lat_min, 6)],
                [round(lng_max, 6), round(lat_max, 6)],
            ],
            "variance_threshold": variance_threshold,
            "dem_source": path,
        }


TOOLS = [
    Tool(name="dem_analyze", description="Analyze DEM terrain: slope, aspect, flow direction, statistics. Uses real DEM if available.", inputSchema={"type": "object", "properties": {"dem_path": {"type": "string", "default": ""}, "cell_size_m": {"type": "number", "default": 0}, "compute_slope": {"type": "boolean", "default": True}, "compute_aspect": {"type": "boolean", "default": True}, "compute_flowdir": {"type": "boolean", "default": True}}, "required": []}),
    Tool(name="flow_accumulation", description="Compute flow accumulation and extract stream network from DEM", inputSchema={"type": "object", "properties": {"dem_path": {"type": "string", "default": ""}, "threshold_cells": {"type": "integer", "default": 100}}, "required": []}),
    Tool(name="watershed_delineate", description="Delineate watershed boundary from outlet point using real DEM", inputSchema={"type": "object", "properties": {"outlet_x": {"type": "number", "default": 0}, "outlet_y": {"type": "number", "default": 0}, "snap_distance_m": {"type": "number", "default": 50}}, "required": []}),
    Tool(name="terrain_profile", description="Generate terrain elevation profile between two points using real DEM", inputSchema={"type": "object", "properties": {"start_x": {"type": "number", "default": 0}, "start_y": {"type": "number", "default": 0}, "end_x": {"type": "number", "default": 0}, "end_y": {"type": "number", "default": 0}, "n_points": {"type": "integer", "default": 30}}, "required": []}),
    Tool(name="dem_render", description="Render DEM as hillshade image overlay and contour lines on map", inputSchema={"type": "object", "properties": {"dem_path": {"type": "string", "default": ""}, "contour_interval": {"type": "number", "default": 20}}, "required": []}),
    Tool(name="point_query", description="Spatial intelligence point query: get elevation, slope, aspect, curvature, TPI, TRI and terrain classification at a point", inputSchema={"type": "object", "properties": {"lng": {"type": "number", "default": 0}, "lat": {"type": "number", "default": 0}, "search_radius_m": {"type": "number", "default": 500}}, "required": []}),
    Tool(name="tin_generate", description="Generate TIN (Triangulated Irregular Network) from DEM with slope-adaptive refinement or fixed spacing", inputSchema={"type": "object", "properties": {"lng_min": {"type": "number", "default": 0}, "lng_max": {"type": "number", "default": 0}, "lat_min": {"type": "number", "default": 0}, "lat_max": {"type": "number", "default": 0}, "max_points": {"type": "integer", "default": 1500}, "refine_steep": {"type": "boolean", "default": True}, "spacing_m": {"type": "number", "default": 0, "description": "Fixed grid spacing in meters (e.g. 20 for 20m mesh). 0=auto by max_points"}}, "required": []}),
    Tool(name="quadtree_subdivide", description="Quadtree adaptive subdivision of DEM based on elevation variance", inputSchema={"type": "object", "properties": {"lng_min": {"type": "number", "default": 0}, "lng_max": {"type": "number", "default": 0}, "lat_min": {"type": "number", "default": 0}, "lat_max": {"type": "number", "default": 0}, "max_depth": {"type": "integer", "default": 4}, "variance_threshold": {"type": "number", "default": 50.0}}, "required": []}),
]


async def scatter_interpolate(
    points_json: str = "",
    method: str = "linear",
    grid_resolution: int = 100,
    bbox: str = "",
    dem_path: str = "",
):
    import numpy as np
    from scipy.interpolate import griddata as scipy_griddata

    if points_json:
        try:
            pts_data = json.loads(points_json)
        except json.JSONDecodeError:
            return {"error": "points_json格式错误，需要JSON数组: [{\"x\":...,\"y\":...,\"z\":...}, ...]"}
        if not isinstance(pts_data, list) or len(pts_data) < 3:
            return {"error": "至少需要3个散点数据"}
        points = np.array([[p.get("x", p.get("lng", 0)), p.get("y", p.get("lat", 0))] for p in pts_data])
        values = np.array([p.get("z", p.get("value", p.get("elevation", 0))) for p in pts_data])
    elif dem_path or REAL_DEM.exists():
        path = _find_dem(dem_path)
        if not path:
            return {"error": "无DEM数据"}
        import rasterio
        with rasterio.open(path) as ds:
            win = _sample_window(ds, 400)
            data = ds.read(1, window=win)
            nodata = ds.nodata if ds.nodata else -9999
            data[data == nodata] = np.nan
            h, w = data.shape
            transform = ds.window_transform(win)
            xs = np.arange(w)
            ys = np.arange(h)
            xx, yy = np.meshgrid(xs, ys)
            valid = ~np.isnan(data)
            n_sample = min(2000, valid.sum())
            idx = np.random.choice(valid.sum(), n_sample, replace=False)
            vy, vx = np.where(valid)
            points = np.column_stack([vx[idx], vy[idx]])
            values = data[vy[idx], vx[idx]]
    else:
        return {"error": "需要提供points_json或DEM数据"}

    x_min, x_max = points[:, 0].min(), points[:, 0].max()
    y_min, y_max = points[:, 1].min(), points[:, 1].max()
    margin_x = (x_max - x_min) * 0.05
    margin_y = (y_max - y_min) * 0.05

    grid_x, grid_y = np.mgrid[
        (x_min - margin_x):(x_max + margin_x):complex(grid_resolution),
        (y_min - margin_y):(y_max + margin_y):complex(grid_resolution)
    ]

    actual_method = method
    method_lower = method.lower()

    if method_lower in ("linear", "nearest", "cubic"):
        grid_z = scipy_griddata(points, values, (grid_x, grid_y), method=method_lower)
    elif method_lower in ("kriging", "ordinary_kriging", "ok"):
        try:
            from pykrige.ok import OrdinaryKriging
            ok = OrdinaryKriging(points[:, 0], points[:, 1], values, variogram_model="linear")
            grid_z, _ = ok.execute("grid", grid_x[:, 0], grid_y[0, :])
        except ImportError:
            from scipy.interpolate import Rbf
            rbf = Rbf(points[:, 0], points[:, 1], values, function="gaussian")
            grid_z = rbf(grid_x, grid_y)
            actual_method = "kriging(RBF-gaussian近似)"
    elif method_lower in ("idw", "inverse_distance"):
        from scipy.spatial import cKDTree
        tree = cKDTree(points)
        grid_flat = np.column_stack([grid_x.ravel(), grid_y.ravel()])
        dists, idxs = tree.query(grid_flat, k=min(12, len(points)))
        dists = np.maximum(dists, 1e-10)
        weights = 1.0 / dists ** 2
        weights /= weights.sum(axis=1, keepdims=True)
        grid_z = np.sum(values[idxs] * weights, axis=1).reshape(grid_x.shape)
        actual_method = "IDW(k=12,p=2)"
    elif method_lower in ("rbf", "rbf_interpolation"):
        from scipy.interpolate import Rbf
        rbf = Rbf(points[:, 0], points[:, 1], values, function="multiquadric")
        grid_z = rbf(grid_x, grid_y)
        actual_method = "RBF(multiquadric)"
    else:
        grid_z = scipy_griddata(points, values, (grid_x, grid_y), method="linear")
        actual_method = "linear(fallback)"

    n_rows, n_cols = grid_z.shape
    step_r = max(1, n_rows // 50)
    step_c = max(1, n_cols // 50)
    grid_preview = np.where(np.isnan(grid_z), None, grid_z)[::step_r, ::step_c].tolist()

    stats = {
        "input_points": len(points),
        "method": actual_method,
        "grid_resolution": f"{grid_resolution}x{grid_resolution}",
        "valid_cells": int((~np.isnan(grid_z)).sum()),
        "total_cells": grid_z.size,
        "z_min": float(np.nanmin(grid_z)) if not np.all(np.isnan(grid_z)) else None,
        "z_max": float(np.nanmax(grid_z)) if not np.all(np.isnan(grid_z)) else None,
        "z_mean": float(np.nanmean(grid_z)) if not np.all(np.isnan(grid_z)) else None,
        "x_range": [float(x_min), float(x_max)],
        "y_range": [float(y_min), float(y_max)],
        "grid_preview": grid_preview,
        "grid_shape": [n_rows, n_cols],
    }
    try:
        import base64, struct
        z_norm = grid_z.copy()
        z_min_v, z_max_v = np.nanmin(z_norm), np.nanmax(z_norm)
        z_range = z_max_v - z_min_v if z_max_v > z_min_v else 1.0
        z_norm = (z_norm - z_min_v) / z_range
        z_norm = np.nan_to_num(z_norm, nan=0.0)
        h, w = z_norm.shape
        header = struct.pack("<2BIHHB", 1, 3, w, h, 0, 8)
        pixels = bytearray()
        colormap = [
            (10, 20, 60), (20, 40, 100), (0, 100, 180), (0, 180, 220),
            (0, 220, 160), (100, 240, 80), (200, 240, 40), (255, 200, 0),
            (255, 140, 0), (255, 60, 0), (180, 0, 0),
        ]
        for r in range(h):
            for c in range(w):
                v = z_norm[r, c]
                idx = min(int(v * (len(colormap) - 1)), len(colormap) - 1)
                R, G, B = colormap[idx]
                pixels.extend([R, G, B, 255])
        raw = header + bytes(pixels)
        import zlib
        compressed = zlib.compress(raw, 9)
        sig = b"\x89PNG\r\n\x1a\n"
        def _png_chunk(ctype, data):
            c = ctype + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
        png_data = sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")
        stats["image_base64"] = base64.b64encode(png_data).decode("ascii")
        stats["bounds"] = [float(y_min - margin_y), float(x_min - margin_x), float(y_max + margin_y), float(x_max + margin_x)]
    except Exception:
        pass
    return stats


TOOLS = [
    Tool(name="dem_analyze", description="Analyze DEM terrain: slope, aspect, flow direction, statistics. Uses real DEM if available.", inputSchema={"type": "object", "properties": {"dem_path": {"type": "string", "default": ""}, "cell_size_m": {"type": "number", "default": 0}, "compute_slope": {"type": "boolean", "default": True}, "compute_aspect": {"type": "boolean", "default": True}, "compute_flowdir": {"type": "boolean", "default": True}}, "required": []}),
    Tool(name="flow_accumulation", description="Compute flow accumulation and extract stream network from DEM", inputSchema={"type": "object", "properties": {"dem_path": {"type": "string", "default": ""}, "threshold_cells": {"type": "integer", "default": 100}}, "required": []}),
    Tool(name="watershed_delineate", description="Delineate watershed boundary from outlet point using real DEM", inputSchema={"type": "object", "properties": {"outlet_x": {"type": "number", "default": 0}, "outlet_y": {"type": "number", "default": 0}, "snap_distance_m": {"type": "number", "default": 50}}, "required": []}),
    Tool(name="terrain_profile", description="Generate terrain elevation profile between two points using real DEM", inputSchema={"type": "object", "properties": {"start_x": {"type": "number", "default": 0}, "start_y": {"type": "number", "default": 0}, "end_x": {"type": "number", "default": 0}, "end_y": {"type": "number", "default": 0}, "n_points": {"type": "integer", "default": 30}}, "required": []}),
    Tool(name="dem_render", description="Render DEM as hillshade image overlay and contour lines on map", inputSchema={"type": "object", "properties": {"dem_path": {"type": "string", "default": ""}, "contour_interval": {"type": "number", "default": 20}}, "required": []}),
    Tool(name="point_query", description="Spatial intelligence point query: get elevation, slope, aspect, curvature, TPI, TRI and terrain classification at a point", inputSchema={"type": "object", "properties": {"lng": {"type": "number", "default": 0}, "lat": {"type": "number", "default": 0}, "search_radius_m": {"type": "number", "default": 500}}, "required": []}),
    Tool(name="tin_generate", description="Generate TIN (Triangulated Irregular Network) from DEM with slope-adaptive refinement or fixed spacing", inputSchema={"type": "object", "properties": {"lng_min": {"type": "number", "default": 0}, "lng_max": {"type": "number", "default": 0}, "lat_min": {"type": "number", "default": 0}, "lat_max": {"type": "number", "default": 0}, "max_points": {"type": "integer", "default": 1500}, "refine_steep": {"type": "boolean", "default": True}, "spacing_m": {"type": "number", "default": 0, "description": "Fixed grid spacing in meters (e.g. 20 for 20m mesh). 0=auto by max_points"}}, "required": []}),
    Tool(name="quadtree_subdivide", description="Quadtree adaptive subdivision of DEM based on elevation variance", inputSchema={"type": "object", "properties": {"lng_min": {"type": "number", "default": 0}, "lng_max": {"type": "number", "default": 0}, "lat_min": {"type": "number", "default": 0}, "lat_max": {"type": "number", "default": 0}, "max_depth": {"type": "integer", "default": 4}, "variance_threshold": {"type": "number", "default": 50.0}}, "required": []}),
    Tool(name="scatter_interpolate", description="散点插值/克里金插值：将离散数据点插值为连续网格表面。支持克里金(Kriging)、IDW、RBF、linear/nearest/cubic方法。输入散点坐标和值，输出插值网格。", inputSchema={"type": "object", "properties": {"points_json": {"type": "string", "description": "JSON array of points: [{\"x\":104.9,\"y\":33.15,\"z\":1200}, ...]. x=lng, y=lat, z=value"}, "method": {"type": "string", "description": "插值方法: kriging(克里金), idw(反距离加权), rbf(径向基函数), linear, nearest, cubic", "default": "linear"}, "grid_resolution": {"type": "integer", "description": "网格分辨率(NxN)", "default": 100}, "dem_path": {"type": "string", "description": "DEM路径，用于采样散点(可选)", "default": ""}}, "required": []}),
]

HANDLERS = {"dem_analyze": dem_analyze, "flow_accumulation": flow_accumulation, "watershed_delineate": watershed_delineate, "terrain_profile": terrain_profile, "dem_render": dem_render, "point_query": point_query, "tin_generate": tin_generate, "quadtree_subdivide": quadtree_subdivide, "scatter_interpolate": scatter_interpolate}

mcp_server = Server("mcp-raster")
sse = SseServerTransport("/messages/")
app = FastAPI(title="MCP Raster Server")
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
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


_heightmap_cache: dict[str, Any] = {}


@app.get("/health")
async def health():
    return {"status": "healthy", "server": "mcp-raster", "tools": len(TOOLS), "real_dem": REAL_DEM.exists()}


@app.get("/api/heightmap")
async def heightmap(size: int = 256):
    import numpy as np

    cache_key = str(size)
    if cache_key in _heightmap_cache:
        return _heightmap_cache[cache_key]

    path = _find_dem()
    if not path:
        return {"error": "No DEM"}
    import rasterio
    from pyproj import Transformer

    with rasterio.open(path) as ds:
        h, w = ds.height, ds.width
        rw = min(size, w)
        rh = min(size, h)
        data = ds.read(1, out_shape=(rh, rw), resampling=rasterio.enums.Resampling.bilinear)
        nodata = ds.nodata if ds.nodata else -9999
        mask = data == nodata
        data[mask] = np.nan
        valid = data[~np.isnan(data)]
        if len(valid) == 0:
            return {"error": "All nodata"}

        fill_val = float(np.nanmin(valid))
        data = np.nan_to_num(data, nan=fill_val)

        transformer = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)
        bl_lng, bl_lat = transformer.transform(ds.bounds.left, ds.bounds.bottom)
        tr_lng, tr_lat = transformer.transform(ds.bounds.right, ds.bounds.top)
        center_x = (ds.bounds.left + ds.bounds.right) / 2
        center_y = (ds.bounds.bottom + ds.bounds.top) / 2
        c_lng, c_lat = transformer.transform(center_x, center_y)

        elev = np.round(data, 1).tolist()
        result = {
            "width": rw, "height": rh,
            "min_elev": round(float(np.nanmin(valid)), 2),
            "max_elev": round(float(np.nanmax(valid)), 2),
            "center_lng": round(c_lng, 6),
            "center_lat": round(c_lat, 6),
            "bounds_wgs84": {"sw": [round(bl_lng, 6), round(bl_lat, 6)], "ne": [round(tr_lng, 6), round(tr_lat, 6)]},
            "elevation": elev,
        }
        _heightmap_cache[cache_key] = result
        return result


@app.post("/call_tool")
async def call_tool_http(body: dict[str, Any]):
    name = body.get("name")
    handler = HANDLERS.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    args = body.get("arguments", {})
    try:
        return await handler(**args)
    except TypeError as e:
        import inspect
        sig = inspect.signature(handler)
        valid = {k: v for k, v in args.items() if k in sig.parameters}
        try:
            return await handler(**valid)
        except Exception as e2:
            return {"error": f"{type(e2).__name__}: {e2}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


app.router.add_api_route("/sse", sse.connect_sse, methods=["GET"])
app.router.add_api_route("/messages/", sse.handle_post_message, methods=["POST"])


def main():
    uvicorn.run(app, host="0.0.0.0", port=5007)


if __name__ == "__main__":
    main()
