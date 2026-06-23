"""Utility functions — SSE formatting, result compression, context trimming, GeoJSON helpers.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import json
import math

import numpy as np


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def detect_ui_action(msg: str) -> str:
    msg_lower = msg.lower().strip()
    if any(k in msg_lower for k in ["3d", "三维", "立体"]):
        if not any(k in msg_lower for k in ["重建", "reconstruct", "建模", "模型"]):
            return "show_3d"
    if any(k in msg_lower for k in ["卫星", "遥感", "sentinel", "landsat"]):
        return "show_satellite"
    if any(k in msg_lower for k in ["知识图谱", "关系图", "实体关系"]):
        return "show_kg"
    if any(k in msg_lower for k in ["数字孪生", "twin"]):
        return "show_twin"
    return ""


def compress_result(tool: str, result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)[:200]
    if "error" in result:
        return f"ERROR: {result['error'][:150]}"
    if tool == "point_query":
        return f"点位: 高程={result.get('elevation_m','?')}m 坡度={result.get('slope_deg','?')}°"
    if tool == "dem_analyze":
        return f"地形: 坡度{result.get('mean_deg','?')}° 坡向={result.get('aspect',{}).get('dominant','?')}"
    if tool == "terrain_profile":
        return f"剖面: 长{result.get('total_distance_m','?')}m 高差{round(result.get('max_elevation_m',0)-result.get('min_elevation_m',0),1)}m"
    if tool == "hydrodynamic_2d_sim":
        return f"模拟: 峰值水深{result.get('peak_max_depth_m','?')}m 面积{result.get('flooded_area_km2','?')}km2"
    if tool == "flood_inundation_map":
        return f"淹没: 面积{result.get('flooded_area_km2','?')}km2 最大水深{result.get('max_depth_m','?')}m"
    if tool == "flood_assessment":
        return f"评估: 风险等级{result.get('risk_level','?')} 受影响{result.get('affected_area_km2','?')}km2"
    if tool == "flood_warning":
        return f"预警: {result.get('warning_level','?')}级 风险={result.get('risk_score','?')}"
    if tool == "weather_forecast":
        daily = result.get("daily", {})
        times = daily.get("time", [])
        precip = daily.get("precipitation_sum", [])
        tmax = daily.get("temperature_2m_max", [])
        tmin = daily.get("temperature_2m_min", [])
        parts = []
        for i in range(min(len(times), 7)):
            line = f"{times[i]}: {precip[i] if i < len(precip) else '?'}mm {tmin[i] if i < len(tmin) else '?'}-{tmax[i] if i < len(tmax) else '?'}°C"
            parts.append(line)
        return "天气预报: " + " | ".join(parts)
    if tool == "get_parameter":
        entries = result.get("results", [])
        return f"参数({result.get('parameter','?')}): {len(entries)}条 " + "; ".join(json.dumps(e, ensure_ascii=False)[:80] for e in entries[:3])
    if tool == "swmm_simulate":
        return f"SWMM: 峰值{result.get('peak_flow_cms','?')}cms 水深{result.get('max_depth_m','?')}m 溢流{result.get('flooding_pct','?')}%"
    if tool == "calibrate_suggest":
        return f"率定: NSE={result.get('nash_sutcliffe','?')} 误差{result.get('error_pct','?')}%"
    return json.dumps(result, ensure_ascii=False)[:200]


def trim_context(messages: list[dict]) -> list[dict]:
    total = sum(len(m.get("content", "")) for m in messages)
    if total <= 16000:
        return messages
    system = messages[0] if messages and messages[0].get("role") == "system" else None
    rest = messages[1:] if system else messages
    removed = 0
    target = total - 16000
    for i, m in enumerate(rest):
        if removed >= target:
            break
        c = m.get("content", "")
        if len(c) > 2000:
            cut = len(c) - 1000
            rest[i] = {**m, "content": c[:1000] + f"\n...[截断{cut}字符]"}
            removed += cut
    result = [system, *rest] if system else rest
    cleaned = [result[0]] if result and result[0].get("role") == "system" else []
    source = result[1:] if cleaned else result
    for m in source:
        if m.get("role") == "tool" and (not cleaned or cleaned[-1].get("role") != "assistant" or not cleaned[-1].get("tool_calls")):
            continue
        cleaned.append(m)
    if len(cleaned) < 2 and messages:
        return messages
    return cleaned


async def stream_words(text: str, chunk_size: int = 3):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def format_tool_summary(server: str, tool: str, result: dict | list) -> str:
    if isinstance(result, list):
        return f"[{tool}] 返回{len(result)}条记录"
    if isinstance(result, dict):
        if "error" in result:
            return f"[{tool}] 错误: {result['error'][:80]}"
        if "geojson" in result:
            gj = result["geojson"]
            n = len(gj.get("features", [])) if isinstance(gj, dict) else 0
            return f"[{tool}] GeoJSON: {n}个要素"
        if "data_points" in result:
            return f"[{tool}] 数据点: {len(result['data_points'])}个"
        keys = list(result.keys())[:5]
        return f"[{tool}] 字段: {', '.join(keys)}"
    return f"[{tool}] 完成"


def bbox_overlap(a: list[float], b: list[float]) -> bool:
    if not a or not b or len(a) != 4 or len(b) != 4:
        return False
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def normalize_auto_tool_result(result: dict) -> dict:
    viz_keys = {"geojson", "points", "data_points", "table", "chart_type", "image_base64", "time_series"}
    top_keys = set(str(k).lower() for k in result.keys())
    has_viz = bool(top_keys & viz_keys)
    if has_viz:
        return result
    flat = {}
    for k, v in result.items():
        if k.startswith("_"):
            flat[k] = v
            continue
        if isinstance(v, dict):
            for vk, vv in v.items():
                if vk.lower() in viz_keys or vk in viz_keys:
                    flat[vk] = vv
                else:
                    flat[f"{k}_{vk}"] = vv
        elif isinstance(v, list):
            flat[k.lower()] = v
        else:
            flat[k] = v
    return flat


def nativefy(obj):
    if isinstance(obj, dict):
        return {k: nativefy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [nativefy(i) for i in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return nativefy(obj.tolist())
    return obj


def fix_polygon_coords(rings):
    """Validate and fix GeoJSON polygon coordinates (close rings, reject NaN/out-of-range)."""
    if not rings:
        return None
    fixed_rings = []
    for ring in rings:
        if not isinstance(ring, list):
            return None
        fixed_ring = []
        for pt in ring:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                return None
            try:
                lon, lat = float(pt[0]), float(pt[1])
            except (TypeError, ValueError):
                return None
            if not (math.isfinite(lon) and math.isfinite(lat)):
                return None
            if abs(lon) > 180 or abs(lat) > 90:
                return None
            fixed_ring.append([lon, lat])
        if len(fixed_ring) < 3:
            return None
        if fixed_ring[0] != fixed_ring[-1]:
            fixed_ring.append(fixed_ring[0])
        fixed_rings.append(fixed_ring)
    return fixed_rings if fixed_rings else None


def fix_line_coords(lines):
    """Validate and fix GeoJSON line string coordinates."""
    if not lines:
        return None
    if isinstance(lines[0], (int, float)):
        return [[float(v)] for v in lines if math.isfinite(float(v))]
    fixed_lines = []
    for line in lines:
        if not isinstance(line, list):
            return None
        fixed = []
        for pt in line:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                return None
            try:
                lon, lat = float(pt[0]), float(pt[1])
            except (TypeError, ValueError):
                return None
            if not (math.isfinite(lon) and math.isfinite(lat)):
                return None
            fixed.append([lon, lat])
        if len(fixed) >= 2:
            fixed_lines.append(fixed)
    return fixed_lines if fixed_lines else None


def sanitize_geojson_result(result: dict) -> dict | None:
    """Clean GeoJSON in a tool result dict — fix coordinates, drop invalid features."""
    if not isinstance(result, dict) or "geojson" not in result:
        return None
    gj = result["geojson"]
    if not isinstance(gj, dict) or "features" not in gj:
        return None
    cleaned_features = []
    for f in gj["features"]:
        if not isinstance(f, dict) or "geometry" not in f:
            cleaned_features.append(f)
            continue
        geom = f["geometry"]
        gtype = geom.get("type", "")
        coords = geom.get("coordinates")
        if gtype in ("Polygon", "MultiPolygon") and coords:
            fixed = fix_polygon_coords(coords)
            if fixed:
                geom["coordinates"] = fixed
                cleaned_features.append(f)
        elif gtype in ("LineString", "MultiLineString") and coords:
            fixed = fix_line_coords(coords)
            if fixed:
                geom["coordinates"] = fixed
                cleaned_features.append(f)
        else:
            cleaned_features.append(f)
    gj["features"] = cleaned_features
    result["geojson"] = gj
    return result
