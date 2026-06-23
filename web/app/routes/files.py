"""File upload routes — geospatial data import, image upload, GLM-4V analysis.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File as FastAPIFile, UploadFile

from app.config import DATA_DIR, UPLOAD_IMG_DIR
from app.multimodal import analyze_image

router = APIRouter()

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/api/upload")
async def upload_file(file: UploadFile = FastAPIFile(...)):
    ext = Path(file.filename or "upload.xxx").suffix.lower()
    if ext not in (".geojson", ".json", ".shp", ".zip", ".gpkg", ".kml", ".csv"):
        return {"error": f"Unsupported format: {ext}"}
    dest = UPLOAD_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)
    info: dict[str, Any] = {"filename": file.filename, "size_bytes": len(content), "path": str(dest)}
    if ext in (".geojson", ".json"):
        try:
            data = json.loads(content)
            if data.get("type") == "FeatureCollection":
                info["format"] = "GeoJSON"
                info["features"] = len(data.get("features", []))
            elif data.get("type") in ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"):
                info["format"] = "GeoJSON"
                info["features"] = 1
        except json.JSONDecodeError:
            pass
    return info


@router.get("/api/uploads")
async def list_uploads():
    files = []
    for f in sorted(UPLOAD_DIR.iterdir()):
        if f.is_file():
            stat = f.stat()
            files.append({"filename": f.name, "size_bytes": stat.st_size, "modified": stat.st_mtime})
    return {"files": files, "upload_dir": str(UPLOAD_DIR)}


@router.post("/api/upload_image")
async def upload_image(file: UploadFile = FastAPIFile(...)):
    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"):
        return {"error": f"Unsupported image format: {ext}"}
    ts = int(time.time() * 1000)
    dest = UPLOAD_IMG_DIR / f"{ts}_{file.filename}"
    content = await file.read()
    dest.write_bytes(content)
    return {"filename": dest.name, "size_bytes": len(content), "path": str(dest)}


@router.post("/api/analyze_image")
async def analyze_image_api(image_base64: str = "", file_path: str = ""):
    if file_path:
        p = Path(file_path)
        if p.exists():
            image_base64 = base64.b64encode(p.read_bytes()).decode()
        else:
            return {"error": "File not found"}
    if not image_base64:
        return {"error": "Provide image_base64 or file_path"}
    result = await analyze_image(image_base64)
    return {"analysis": result}
