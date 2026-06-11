from __future__ import annotations

import json
import re
import sqlite3
import time

import httpx
import structlog

from app.config import DATA_DIR, STUDY_BBOX, logger


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
