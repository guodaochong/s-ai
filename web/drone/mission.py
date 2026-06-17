import math
import logging
import numpy as np

logger = logging.getLogger(__name__)

MISSION_PROFILES = {
    "flood_inspect": {
        "name": "洪水巡查",
        "altitude_m": 80,
        "speed_ms": 8,
        "gimbal_deg": -60,
        "spacing_m": 120,
        "pattern": "snake",
    },
    "dam_inspect": {
        "name": "堤坝巡检",
        "altitude_m": 50,
        "speed_ms": 5,
        "gimbal_deg": -45,
        "spacing_m": 80,
        "pattern": "linear",
    },
    "search_rescue": {
        "name": "搜救搜索",
        "altitude_m": 40,
        "speed_ms": 4,
        "gimbal_deg": -90,
        "spacing_m": 60,
        "pattern": "spiral",
    },
    "damage_assess": {
        "name": "灾后评估",
        "altitude_m": 120,
        "speed_ms": 10,
        "gimbal_deg": -90,
        "spacing_m": 100,
        "pattern": "grid",
    },
}


def identify_risk_hotspots(
    building_impacts: list[dict],
    depth_grid: list[list[float]],
    grid_lats: list[float],
    grid_lons: list[float],
    bbox: list[float],
    max_waypoints: int = 15,
) -> list[dict]:
    hotspots = []

    submerged = [b for b in building_impacts if b["flood_status"] == "submerged"]
    partial = [b for b in building_impacts if b["flood_status"] == "partial"]

    building_clusters = _cluster_buildings(submerged + partial, max_clusters=6)
    for i, cluster in enumerate(building_clusters):
        cx = sum(b["center"][0] for b in cluster) / len(cluster)
        cy = sum(b["center"][1] for b in cluster) / len(cluster)
        risk = sum(b["max_flood_depth_m"] for b in cluster) / len(cluster)
        hotspots.append({
            "lat": cy, "lon": cx,
            "type": "building_cluster",
            "risk_score": round(min(risk * len(cluster) / 10, 10), 1),
            "n_buildings": len(cluster),
            "label": f"建筑淹没区{i+1}({len(cluster)}栋)",
        })

    if depth_grid and grid_lats and grid_lons:
        arr = np.array(depth_grid)
        gn, gm = arr.shape
        n_river = min(4, max_waypoints - len(hotspots))
        if n_river > 0 and arr.max() > 0.1:
            threshold = max(arr.mean() + arr.std(), 0.3)
            deep_mask = arr > threshold
            if deep_mask.any():
                labeled = _label_clusters(deep_mask)
                for label_id in range(1, min(labeled.max() + 1, n_river + 1)):
                    mask = labeled == label_id
                    if mask.sum() < 2:
                        continue
                    rows, cols = np.where(mask)
                    cr = int(rows.mean())
                    cc = int(cols.mean())
                    if cr < len(grid_lats) and cc < len(grid_lons):
                        hotspots.append({
                            "lat": grid_lats[cr],
                            "lon": grid_lons[cc],
                            "type": "deep_water",
                            "risk_score": round(float(arr[cr, cc]), 1),
                            "label": f"深水区({float(arr[cr,cc]):.1f}m)",
                        })

    hotspots.sort(key=lambda h: h["risk_score"], reverse=True)
    return hotspots[:max_waypoints]


def _cluster_buildings(buildings: list[dict], max_clusters: int = 6) -> list[list[dict]]:
    if not buildings:
        return []
    clusters = [[buildings[0]]]
    for b in buildings[1:]:
        merged = False
        for cluster in clusters:
            for existing in cluster:
                dx = abs(b["center"][0] - existing["center"][0])
                dy = abs(b["center"][1] - existing["center"][1])
                if dx < 0.003 and dy < 0.003:
                    cluster.append(b)
                    merged = True
                    break
            if merged:
                break
        if not merged:
            clusters.append([b])
    clusters.sort(key=len, reverse=True)
    return clusters[:max_clusters]


def _label_clusters(mask: np.ndarray) -> np.ndarray:
    from scipy.ndimage import label
    labeled, _ = label(mask)
    return labeled


def plan_mission(
    hotspots: list[dict],
    bbox: list[float],
    profile_name: str = "flood_inspect",
    takeoff_lat: float = 0,
    takeoff_lon: float = 0,
    battery_min: int = 25,
) -> dict:
    profile = MISSION_PROFILES.get(profile_name, MISSION_PROFILES["flood_inspect"])

    if takeoff_lat == 0 or takeoff_lon == 0:
        takeoff_lon = (bbox[0] + bbox[2]) / 2
        takeoff_lat = (bbox[1] + bbox[3]) / 2

    waypoints = [{
        "seq": 0,
        "lat": takeoff_lat,
        "lon": takeoff_lon,
        "alt_m": 0,
        "action": "takeoff",
        "label": "起飞点",
    }]

    ordered = _optimize_path(hotspots, takeoff_lat, takeoff_lon)

    alt = profile["altitude_m"]
    for i, hs in enumerate(ordered):
        waypoints.append({
            "seq": i + 1,
            "lat": hs["lat"],
            "lon": hs["lon"],
            "alt_m": alt,
            "action": "waypoint",
            "gimbal_pitch": profile["gimbal_deg"],
            "speed_ms": profile["speed_ms"],
            "label": hs.get("label", f"航点{i+1}"),
            "risk_score": hs.get("risk_score", 0),
            "type": hs.get("type", ""),
        })

    waypoints.append({
        "seq": len(ordered) + 1,
        "lat": takeoff_lat,
        "lon": takeoff_lon,
        "alt_m": 0,
        "action": "land",
        "label": "降落点",
    })

    total_dist_m = 0
    for i in range(len(waypoints) - 1):
        total_dist_m += _haversine_m(
            waypoints[i]["lat"], waypoints[i]["lon"],
            waypoints[i+1]["lat"], waypoints[i+1]["lon"],
        )

    flight_time_min = total_dist_m / (profile["speed_ms"] * 60) if profile["speed_ms"] > 0 else 0
    coverage_km2 = abs(bbox[2]-bbox[0]) * abs(bbox[3]-bbox[1]) * 111 * 111 * math.cos(math.radians((bbox[1]+bbox[3])/2)) / 100

    risk_scores = [w.get("risk_score", 0) for w in waypoints if w.get("risk_score", 0) > 0]
    avg_risk = sum(risk_scores) / max(len(risk_scores), 1)

    return {
        "drone_mission": True,
        "mission_type": profile_name,
        "mission_name": profile["name"],
        "waypoints": waypoints,
        "n_waypoints": len(ordered),
        "total_distance_km": round(total_dist_m / 1000, 2),
        "estimated_flight_min": round(flight_time_min, 1),
        "battery_required_min": math.ceil(flight_time_min * 1.3),
        "battery_sufficient": flight_time_min * 1.3 < battery_min,
        "altitude_m": alt,
        "speed_ms": profile["speed_ms"],
        "coverage_km2": round(coverage_km2, 1),
        "avg_risk_score": round(avg_risk, 1),
        "takeoff_point": [takeoff_lon, takeoff_lat],
        "bbox": bbox,
        "profile": profile,
        "kml": _generate_kml(waypoints, profile["name"]),
    }


def _optimize_path(hotspots: list[dict], start_lat: float, start_lon: float) -> list[dict]:
    if not hotspots:
        return []

    remaining = list(hotspots)
    ordered = []
    cur_lat, cur_lon = start_lat, start_lon

    while remaining:
        nearest = min(remaining, key=lambda h: _haversine_m(cur_lat, cur_lon, h["lat"], h["lon"]))
        ordered.append(nearest)
        cur_lat, cur_lon = nearest["lat"], nearest["lon"]
        remaining.remove(nearest)

    if len(ordered) > 4:
        ordered = _two_opt(ordered, start_lat, start_lon)

    return ordered


def _two_opt(route: list[dict], start_lat: float, start_lon: float) -> list[dict]:
    best = list(route)
    improved = True
    iterations = 0
    while improved and iterations < 20:
        improved = False
        iterations += 1
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best) - 1):
                new_route = best[:i] + best[i:j+1][::-1] + best[j+1:]
                d_old = _route_distance(best, start_lat, start_lon)
                d_new = _route_distance(new_route, start_lat, start_lon)
                if d_new < d_old - 1:
                    best = new_route
                    improved = True
        best = _route_distance_optimize(best)
    return best


def _route_distance(route: list[dict], start_lat: float, start_lon: float) -> float:
    total = _haversine_m(start_lat, start_lon, route[0]["lat"], route[0]["lon"])
    for i in range(len(route) - 1):
        total += _haversine_m(route[i]["lat"], route[i]["lon"], route[i+1]["lat"], route[i+1]["lon"])
    total += _haversine_m(route[-1]["lat"], route[-1]["lon"], start_lat, start_lon)
    return total


def _route_distance_optimize(route): return route


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _generate_kml(waypoints: list[dict], name: str) -> str:
    coords = " ".join(f"{w['lon']},{w['lat']},{w.get('alt_m',0)}" for w in waypoints)
    placemarks = ""
    for w in waypoints:
        icon = "📌" if w["action"] == "waypoint" else ("🛫" if w["action"] == "takeoff" else "🛬")
        placemarks += f"""
        <Placemark>
          <name>{icon} {w['label']}</name>
          <Point><coordinates>{w['lon']},{w['lat']},{w.get('alt_m',0)}</coordinates></Point>
        </Placemark>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{name}</name>
    <Style id="line"><LineStyle><color>ff00aaff</color><width>3</width></LineStyle></Style>
    <Placemark>
      <name>航线</name>
      <styleUrl>#line</styleUrl>
      <LineString><tessellate>1</tessellate><coordinates>{coords}</coordinates></LineString>
    </Placemark>{placemarks}
  </Document>
</kml>"""
