from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import structlog

logger = structlog.get_logger(__name__)


async def read_vector(
    file_path: str,
    layer: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    where: str | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    kwargs: dict[str, Any] = {}
    if layer:
        kwargs["layer"] = layer
    if bbox:
        kwargs["bbox"] = bbox
    if where:
        kwargs["where"] = where

    gdf = gpd.read_file(str(path), **kwargs)
    return {
        "type": "FeatureCollection",
        "features": json_features(gdf),
        "crs": str(gdf.crs),
        "feature_count": len(gdf),
        "columns": list(gdf.columns),
    }


async def write_vector(
    data: dict[str, Any],
    file_path: str,
    driver: str = "GeoJSON",
    layer: str | None = None,
) -> dict[str, Any]:
    gdf = gpd.GeoDataFrame.from_features(data.get("features", []))
    if "crs" in data:
        gdf = gdf.set_crs(data["crs"])

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = {"driver": driver}
    if layer:
        kwargs["layer"] = layer

    gdf.to_file(str(path), **kwargs)
    return {
        "status": "written",
        "file_path": str(path),
        "feature_count": len(gdf),
        "driver": driver,
    }


def json_features(gdf: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    from shapely.geometry import mapping
    features: list[dict[str, Any]] = []
    cols = [c for c in gdf.columns if c != "geometry"]
    for _, row in gdf.iterrows():
        geom = row.get("geometry")
        if geom is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {k: _serialize(row[k]) for k in cols},
        })
    return features


def _serialize(val: Any) -> Any:
    import math
    import numpy as np
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        v = float(val)
        return None if math.isnan(v) else v
    if isinstance(val, np.ndarray):
        return val.tolist()
    if isinstance(val, float) and math.isnan(val):
        return None
    return val


UPLOAD_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "uploads"


async def import_network(
    file_path: str = "",
    file_name: str = "",
    network_type: str = "auto",
) -> dict[str, Any]:
    if file_name and not file_path:
        file_path = str(UPLOAD_DIR / file_name)
    if not file_path:
        return {"error": "Provide file_path or file_name"}

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    try:
        gdf = gpd.read_file(str(path))
    except Exception as e:
        return {"error": f"Failed to read: {e}"}

    geom_types = gdf.geometry.geom_type.value_counts().to_dict()
    total = len(gdf)
    bounds = gdf.total_bounds.tolist()

    columns = [c for c in gdf.columns if c != "geometry"]
    sample = gdf[columns].head(5).to_dict(orient="records")
    for row in sample:
        for k, v in row.items():
            row[k] = _serialize(v)

    detected = network_type
    if network_type == "auto":
        has_line = any(t in geom_types for t in ("LineString", "MultiLineString"))
        has_point = any(t in geom_types for t in ("Point", "MultiPoint"))
        if has_line and has_point:
            detected = "mixed"
        elif has_line:
            detected = "pipe_network"
        elif has_point:
            detected = "nodes"
        else:
            detected = "unknown"

    features = json_features(gdf)

    return {
        "file": str(path),
        "network_type": detected,
        "feature_count": total,
        "geometry_types": geom_types,
        "bounds": bounds,
        "columns": columns,
        "sample_records": sample,
        "geojson": {"type": "FeatureCollection", "features": features},
    }
