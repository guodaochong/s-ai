import httpx
import math
import logging

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"


async def fetch_osm_buildings(bbox: list[float]) -> list[dict]:
    south, west, north, east = bbox[1], bbox[0], bbox[3], bbox[2]
    query = (
        f'[out:json][timeout:25];'
        f'(way["building"]({south},{west},{north},{east});'
        f'relation["building"]({south},{west},{north},{east}););'
        f'out geom;'
    )
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(OVERPASS_URL, data={"data": query})
        r.raise_for_status()
        data = r.json()

    features = []
    for el in data.get("elements", []):
        if el["type"] == "way":
            geom = el.get("geometry", [])
            if len(geom) < 3:
                continue
            coords = [[p["lon"], p["lat"]] for p in geom]
            coords.append(coords[0])
        elif el["type"] == "relation":
            members = el.get("members", [])
            outer = next((m for m in members if m.get("role") == "outer"), None)
            if not outer or not outer.get("geometry"):
                continue
            geom = outer["geometry"]
            if len(geom) < 3:
                continue
            coords = [[p["lon"], p["lat"]] for p in geom]
            coords.append(coords[0])
        else:
            continue

        tags = el.get("tags", {})
        area_m2 = _polygon_area_m2(coords)

        levels = tags.get("building:levels")
        height_m = tags.get("height")
        if height_m:
            try:
                est_h = int(float(height_m))
            except ValueError:
                est_h = _estimate_height_from_area(area_m2)
        elif levels:
            try:
                est_h = max(3, int(float(levels)) * 3)
            except ValueError:
                est_h = _estimate_height_from_area(area_m2)
        else:
            est_h = _estimate_height_from_area(area_m2)

        btype_raw = tags.get("building", "yes")
        bname = tags.get("name", "")
        btype = _map_osm_type(btype_raw, area_m2, est_h)

        cx_lon = sum(c[0] for c in coords[:-1]) / max(len(coords) - 1, 1)
        cy_lat = sum(c[1] for c in coords[:-1]) / max(len(coords) - 1, 1)

        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "height_m": est_h,
                "area_m2": round(area_m2, 1),
                "width_m": round(math.sqrt(area_m2) * 0.8, 1),
                "length_m": round(math.sqrt(area_m2) * 1.2, 1),
                "confidence": 1.0,
                "center": [round(cx_lon, 7), round(cy_lat, 7)],
                "building_type": btype["type"],
                "type_icon": btype["icon"],
                "type_color": btype["color"],
                "name": bname,
                "osm_type": btype_raw,
            },
        })

    logger.info(f"[OSM] Fetched {len(features)} buildings from Overpass")
    return features


def _polygon_area_m2(coords: list[list[float]]) -> float:
    if len(coords) < 4:
        return 0
    lat_mid = sum(c[1] for c in coords[:-1]) / max(len(coords) - 1, 1)
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_mid))

    area = 0
    n = len(coords) - 1
    for i in range(n):
        j = (i + 1) % n
        xi = coords[i][0] * m_per_deg_lon
        yi = coords[i][1] * m_per_deg_lat
        xj = coords[j][0] * m_per_deg_lon
        yj = coords[j][1] * m_per_deg_lat
        area += xi * yj - xj * yi
    return abs(area) / 2


def _estimate_height_from_area(area_m2: float) -> int:
    if area_m2 < 50:
        return 3
    if area_m2 < 200:
        return 6
    if area_m2 < 500:
        return 9
    if area_m2 < 1000:
        return 12
    if area_m2 < 2000:
        return 15
    return 20


def _map_osm_type(osm_type: str, area_m2: float, height_m: int) -> dict:
    t = osm_type.lower()
    if t in ("residential", "apartments", "house", "detached", "terrace", "dormitory"):
        if height_m >= 12:
            return {"type": "高层住宅", "icon": "🏢", "color": "#60a5fa"}
        return {"type": "低层住宅", "icon": "🏠", "color": "#4ade80"}
    if t in ("commercial", "retail", "shop", "mall", "supermarket"):
        return {"type": "商业办公", "icon": "🏬", "color": "#22d3ee"}
    if t in ("industrial", "warehouse", "factory", "manufacture"):
        return {"type": "工业仓储", "icon": "🏭", "color": "#f59e0b"}
    if t in ("school", "university", "college", "hospital", "government", "public", "civic", "church", "kindergarten"):
        return {"type": "公共设施", "icon": "🏫", "color": "#a78bfa"}
    if t in ("garage", "garages", "shed", "hut", "carport", "service"):
        return {"type": "附属设施", "icon": "🔧", "color": "#94a3b8"}
    if area_m2 < 80:
        return {"type": "附属设施", "icon": "🔧", "color": "#94a3b8"}
    if area_m2 > 1500 and height_m <= 9:
        return {"type": "工业仓储", "icon": "🏭", "color": "#f59e0b"}
    if height_m >= 12:
        return {"type": "商业办公", "icon": "🏬", "color": "#22d3ee"}
    return {"type": "低层住宅", "icon": "🏠", "color": "#4ade80"}
