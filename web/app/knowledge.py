from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time

import httpx
import structlog

from app.config import DATA_DIR, STUDY_BBOX, logger

_precip_cache: dict[str, tuple[float, dict]] = {}


class SpatialKG:
    def __init__(self):
        self.db_path = DATA_DIR / "spatial_kg.db"
        self._init()

    def _init(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, type TEXT, properties TEXT);
                CREATE TABLE IF NOT EXISTS relations (id INTEGER PRIMARY KEY AUTOINCREMENT, from_name TEXT, relation TEXT, to_name TEXT, confidence REAL DEFAULT 1.0);
            """)
            for name, typ, props in [
                ("迭部县", "region", '{"lat":33.19,"lon":104.89}'),
                ("白龙江", "river", '{"length_km":500}'),
                ("DEM_LBH", "dataset", '{"resolution":"0.5m","size":"3GB","crs":"EPSG:4544"}'),
                ("研究区", "area", '{"elev_min":790,"elev_max":1800}'),
            ]:
                conn.execute("INSERT OR IGNORE INTO entities(name,type,properties) VALUES(?,?,?)", (name, typ, props))
            for fr, rel, to in [("迭部县", "contains", "白龙江"), ("DEM_LBH", "covers", "迭部县"), ("白龙江", "flows_through", "迭部县"), ("研究区", "located_in", "迭部县")]:
                conn.execute("INSERT OR IGNORE INTO relations(from_name,relation,to_name) VALUES(?,?,?)", (fr, rel, to))

    def query_entities(self, name: str = "", type: str = "") -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            sql = "SELECT name,type,properties FROM entities WHERE 1=1"
            params = []
            if name:
                sql += " AND name LIKE ?"
                params.append(f"%{name}%")
            if type:
                sql += " AND type = ?"
                params.append(type)
            rows = conn.execute(sql, params).fetchall()
        return [{"name": r[0], "type": r[1], "properties": json.loads(r[2]) if r[2] else {}} for r in rows]

    def query_relations(self, entity: str = "") -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            sql = "SELECT from_name,relation,to_name,confidence FROM relations WHERE 1=1"
            params = []
            if entity:
                sql += " AND (from_name LIKE ? OR to_name LIKE ?)"
                params.extend([f"%{entity}%", f"%{entity}%"])
            rows = conn.execute(sql, params).fetchall()
        return [{"from": r[0], "relation": r[1], "to": r[2], "confidence": r[3]} for r in rows]

    def add_entity(self, name: str, typ: str, properties: str = "{}"):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT OR IGNORE INTO entities(name,type,properties) VALUES(?,?,?)", (name, typ, properties))

    def add_relation(self, fr: str, rel: str, to: str, confidence: float = 1.0):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT INTO relations(from_name,relation,to_name,confidence) VALUES(?,?,?,?)", (fr, rel, to, confidence))


kg = SpatialKG()


class DocRAG:
    def __init__(self):
        self.db_path = DATA_DIR / "doc_rag.db"
        self._init()

    def _init(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT, content TEXT, source TEXT, tags TEXT, ts REAL
                );
                CREATE TABLE IF NOT EXISTS doc_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id INTEGER, chunk_text TEXT, chunk_idx INTEGER,
                    FOREIGN KEY(doc_id) REFERENCES documents(id)
                );
            """)

    def add_document(self, title: str, content: str, source: str = "", tags: str = "") -> int:
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute("INSERT INTO documents(title,content,source,tags,ts) VALUES(?,?,?,?,?)",
                                  (title, content[:50000], source, tags, time.time()))
            doc_id = cursor.lastrowid
            chunks = [content[i:i + 500] for i in range(0, len(content), 500)]
            for idx, chunk in enumerate(chunks):
                conn.execute("INSERT INTO doc_chunks(doc_id,chunk_text,chunk_idx) VALUES(?,?,?)", (doc_id, chunk, idx))
            return doc_id

    def search(self, query: str, limit: int = 5) -> list[dict]:
        words = re.findall(r"[\u4e00-\u9fff\w]{2,}", query)
        if not words:
            return []
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT id,title,content,source,tags FROM documents").fetchall()
        results = []
        for r in rows:
            text = f"{r[1]} {r[2]} {r[4]}"
            score = sum(2 if w in r[1] else (1 if w in text else 0) for w in words)
            if score > 0:
                results.append({"id": r[0], "title": r[1], "content": r[2][:1000], "source": r[3], "tags": r[4], "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]


rag = DocRAG()


async def search_satellite(bbox: list[float] | None = None, date_start: str = "", date_end: str = "") -> dict:
    bbox = bbox or STUDY_BBOX
    datetime_str = f"{date_start}/{date_end}" if date_start and date_end else "2024-01-01/2026-06-07"
    url = "https://earth-search.aws.element84.com/v1/search"
    payload = {"bbox": bbox, "datetime": datetime_str, "collections": ["sentinel-2-l2a"], "limit": 5}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            features = []
            for f in data.get("features", [])[:5]:
                props = f.get("properties", {})
                features.append({
                    "id": f.get("id", ""), "datetime": props.get("datetime", ""),
                    "cloud_cover": props.get("eo:cloud_cover", "?"),
                    "bbox": f.get("bbox", []), "assets": list(f.get("assets", {}).keys())[:5]
                })
            return {"total": data.get("numberReturned", 0), "features": features}
    except Exception as e:
        return {"error": str(e)[:200]}


async def get_weather(lat: float = 33.19, lon: float = 104.89, days: int = 3) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max&forecast_days={days}")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)[:200]}


CITY_COORDS = {
    "天水": (105.7249, 34.5809), "兰州": (103.8343, 36.0611), "西安": (108.9398, 34.3416),
    "北京": (116.4074, 39.9042), "上海": (121.4737, 31.2304), "成都": (104.0657, 30.5723),
    "重庆": (106.5516, 29.5630), "武汉": (114.3055, 30.5928), "南京": (118.7969, 32.0603),
    "杭州": (120.1551, 30.2741), "广州": (113.2644, 23.1291), "深圳": (114.0579, 22.5431),
    "陇南": (104.9219, 33.3886), "定西": (104.6264, 35.5796), "平凉": (106.6652, 35.5428),
    "白龙江": (104.9219, 33.3886), "嘉陵江": (106.1080, 32.5400), "渭河": (108.9398, 34.3416),
    "黄河": (106.2309, 38.4872), "洮河": (103.8343, 35.3000), "大夏河": (102.5000, 35.5000),
    "西汉水": (105.7000, 33.8000), "通天河": (104.3000, 33.0000),
    "庆阳": (107.6380, 35.7342), "酒泉": (98.4941, 39.7320), "张掖": (100.4496, 38.9252),
    "武威": (102.6385, 37.9283), "白银": (104.1386, 36.5447), "嘉峪关": (98.2773, 39.7865),
    "金昌": (102.1880, 38.5160), "临夏": (103.2104, 35.6011), "甘南": (102.9109, 34.9834),
    "赤峰": (118.8889, 42.2576), "呼和浩特": (111.7519, 40.8414), "沈阳": (123.4290, 41.7969),
    "哈尔滨": (126.5358, 45.8023), "长春": (125.3245, 43.8868), "天津": (117.1901, 39.1252),
    "郑州": (113.6253, 34.7466), "长沙": (112.9388, 28.2282), "南昌": (115.8581, 28.6829),
    "合肥": (117.2272, 31.8206), "福州": (119.2964, 26.0745), "昆明": (102.8329, 24.8801),
    "贵阳": (106.7135, 26.5783), "拉萨": (91.1409, 29.6457), "银川": (106.2309, 38.4872),
    "西宁": (101.7782, 36.6171), "乌鲁木齐": (87.6168, 43.8256), "太原": (112.5489, 37.8706),
    "石家庄": (114.5149, 38.0428), "济南": (117.1205, 36.6510), "海口": (110.3312, 20.0317),
    "南宁": (108.3669, 22.8170), "包头": (109.8403, 40.6574),
}


async def geocode_city(name: str) -> tuple[float, float] | None:
    for city, coord in CITY_COORDS.items():
        if city in name:
            return coord
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": name, "format": "json", "limit": 1, "accept-language": "zh"},
                headers={"User-Agent": "S-AI/1.0"},
            )
            data = resp.json()
            if data:
                return float(data[0]["lon"]), float(data[0]["lat"])
    except Exception as exc:
        logger.warning("[Knowledge] geocode failed", city=name, error=str(exc)[:200])
    return None



async def fetch_precipitation_grid(
    bbox: list[float] | None = None,
    date_start: str = "",
    date_end: str = "",
    grid_size: int = 8,
    forecast_mode: bool = False,
    location: str = "",
) -> dict:
    from datetime import datetime, timedelta

    if location:
        coord = await geocode_city(location)
        if coord:
            cx, cy = coord
            half = 1.0
            bbox = [cx - half, cy - half, cx + half, cy + half]
    if not bbox or len(bbox) < 4:
        bbox = [104.5, 33.0, 105.3, 33.5]
    west, south, east, north = bbox[0], bbox[1], bbox[2], bbox[3]

    min_span = 0.5
    cx, cy = (west + east) / 2, (south + north) / 2
    if abs(east - west) < min_span or abs(north - south) < min_span:
        west = cx - min_span / 2
        east = cx + min_span / 2
        south = cy - min_span / 2
        north = cy + min_span / 2

    gs = max(4, min(grid_size, 12))

    today = datetime.now().strftime("%Y-%m-%d")
    if forecast_mode:
        date_start = today
        date_end = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    else:
        if not date_end:
            date_end = today
        if not date_start:
            date_start = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    cache_key = f"{west:.2f}_{south:.2f}_{east:.2f}_{north:.2f}_{date_start}_{date_end}_{gs}"
    if cache_key in _precip_cache and time.time() - _precip_cache[cache_key][0] < 600:
        return _precip_cache[cache_key][1]

    lats: list[float] = []
    lons: list[float] = []
    for i in range(gs):
        lat = south + (north - south) * i / (gs - 1)
        for j in range(gs):
            lon = west + (east - west) * j / (gs - 1)
            lats.append(round(lat, 4))
            lons.append(round(lon, 4))

    seen: dict[str, int] = {}
    uniq_lats: list[float] = []
    uniq_lons: list[float] = []
    remap: list[int] = []
    for i in range(len(lats)):
        key = f"{lats[i]:.4f},{lons[i]:.4f}"
        if key not in seen:
            seen[key] = len(uniq_lats)
            uniq_lats.append(lats[i])
            uniq_lons.append(lons[i])
        remap.append(seen[key])

    lat_str = ",".join(str(x) for x in uniq_lats)
    lon_str = ",".join(str(x) for x in uniq_lons)

    is_forecast = date_end >= today and date_start >= today
    if is_forecast:
        base_url = "https://api.open-meteo.com/v1/forecast"
        model_param = ""
    else:
        base_url = "https://archive-api.open-meteo.com/v1/archive"
        model_param = "&models=era5_land"
    url = (
        f"{base_url}?latitude={lat_str}&longitude={lon_str}"
        f"&hourly=precipitation&start_date={date_start}&end_date={date_end}&timezone=Asia/Shanghai{model_param}"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json()
    except Exception as e:
        return {"error": f"Open-Meteo API请求失败: {str(e)[:150]}"}

    if isinstance(raw, list):
        data_list = raw
    else:
        data_list = [raw]

    time_labels: list[str] = []
    uniq_vals: list[list[float]] = []
    for idx, pt in enumerate(data_list):
        hourly = pt.get("hourly", {})
        times = hourly.get("time", [])
        vals = hourly.get("precipitation", [])
        if not time_labels:
            time_labels = times
        uniq_vals.append([float(v) if v is not None else 0.0 for v in vals])

    precip_matrix: list[list[float]] = []
    for t_idx in range(len(time_labels)):
        frame = []
        for grid_idx in range(len(lats)):
            uidx = remap[grid_idx]
            frame.append(uniq_vals[uidx][t_idx] if t_idx < len(uniq_vals[uidx]) else 0.0)
        precip_matrix.append(frame)

    if not time_labels or not precip_matrix:
        return {"error": "未获取到降水数据"}

    grid_lats = []
    grid_lons = []
    for i in range(gs):
        for j in range(gs):
            grid_lats.append(lats[i * gs + j])
            grid_lons.append(lons[i * gs + j])

    area_avg: list[float] = []
    all_vals: list[float] = []
    for frame in precip_matrix:
        avg = sum(frame) / len(frame) if frame else 0
        area_avg.append(round(avg, 2))
        all_vals.extend(frame)

    max_val = max(all_vals) if all_vals else 0
    mean_val = sum(all_vals) / len(all_vals) if all_vals else 0
    total_val = sum(area_avg)

    peak_idx = area_avg.index(max(area_avg)) if area_avg else 0
    peak_time = time_labels[peak_idx] if peak_idx < len(time_labels) else ""

    storm_centers: list[dict] = []
    for t_idx, frame in enumerate(precip_matrix):
        if not frame or max(frame) <= 0:
            continue
        max_val_t = max(frame)
        g_idx = frame.index(max_val_t)
        sc_lat = grid_lats[g_idx] if g_idx < len(grid_lats) else 0
        sc_lon = grid_lons[g_idx] if g_idx < len(grid_lons) else 0
        storm_centers.append({
            "time": time_labels[t_idx],
            "lat": round(sc_lat, 4),
            "lon": round(sc_lon, 4),
            "mm": round(max_val_t, 2),
            "place": "",
        })

    geocoded: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=10) as gc:
        for sc in storm_centers:
            loc_key = f"{sc['lat']:.3f},{sc['lon']:.3f}"
            if loc_key in geocoded:
                sc["place"] = geocoded[loc_key]
                continue
            try:
                resp = await gc.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={"lat": sc["lat"], "lon": sc["lon"], "format": "json", "zoom": 16, "accept-language": "zh"},
                    headers={"User-Agent": "S-AI/1.0"},
                )
                addr = resp.json().get("address", {})
                parts = [addr.get("village"), addr.get("hamlet"), addr.get("town"), addr.get("county")]
                place = "·".join([p for p in parts if p]) or addr.get("county", "")
                sc["place"] = place
                geocoded[loc_key] = place
            except Exception as exc:
                logger.warning("[Knowledge] reverse geocode failed", lat=sc["lat"], lon=sc["lon"], error=str(exc)[:200])
            await asyncio.sleep(0.2)

    peak_grid_idx = precip_matrix[peak_idx].index(max(precip_matrix[peak_idx])) if precip_matrix[peak_idx] else 0
    peak_lat = grid_lats[peak_grid_idx] if peak_grid_idx < len(grid_lats) else 0
    peak_lon = grid_lons[peak_grid_idx] if peak_grid_idx < len(grid_lons) else 0

    result = {
        "precipitation_grid": True,
        "bbox": [west, south, east, north],
        "date_start": date_start,
        "date_end": date_end,
        "grid_size": gs,
        "data_source": "ERA5-Land 0.1° (~9km)" if not is_forecast else "Open-Meteo Forecast (~11km)",
        "resolution_km": 9 if not is_forecast else 11,
        "time_steps": time_labels,
        "grid_lats": grid_lats,
        "grid_lons": grid_lons,
        "precipitation_matrix": precip_matrix,
        "area_average_series": [{"time": t, "value_mm": v} for t, v in zip(time_labels, area_avg)],
        "storm_centers": storm_centers,
        "stats": {
            "max_mm": round(max_val, 2),
            "mean_mm": round(mean_val, 2),
            "total_area_avg_mm": round(total_val, 2),
            "peak_time": peak_time,
            "peak_intensity_mm_hr": round(max(area_avg) if area_avg else 0, 2),
            "peak_center": {"lat": round(peak_lat, 4), "lon": round(peak_lon, 4)},
        },
    }

    _precip_cache[cache_key] = (time.time(), result)
    return result
