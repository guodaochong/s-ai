from __future__ import annotations

from typing import Any

import geopandas as gpd
import structlog
from shapely.geometry import shape, mapping

logger = structlog.get_logger(__name__)


async def spatial_query(
    geometry_a: dict[str, Any],
    geometry_b: dict[str, Any],
    relation: str = "intersects",
) -> dict[str, Any]:
    geom_a = shape(geometry_a)
    geom_b = shape(geometry_b)

    predicates: dict[str, Any] = {
        "intersects": geom_a.intersects,
        "contains": geom_a.contains,
        "within": geom_a.within,
        "touches": geom_a.touches,
        "crosses": geom_a.crosses,
        "overlaps": geom_a.overlaps,
        "covers": geom_a.covers,
        "covered_by": lambda: geom_a.covered_by(geom_b),
        "equals": geom_a.equals,
        "disjoint": geom_a.disjoint,
    }

    fn = predicates.get(relation)
    if fn is None:
        raise ValueError(f"Unknown relation: {relation}. Valid: {list(predicates.keys())}")

    return {"result": fn(geom_b), "relation": relation}


async def buffer(
    geometry: dict[str, Any],
    distance: float = 100.0,
    unit: str = "meters",
    resolution: int = 16,
) -> dict[str, Any]:
    geom = shape(geometry)
    buffered = geom.buffer(distance, resolution=resolution)
    result = mapping(buffered)
    return {"geometry": result, "crs": "EPSG:4326"}


async def overlay(
    geometry_a: dict[str, Any],
    geometry_b: dict[str, Any],
    operation: str = "intersection",
) -> dict[str, Any]:
    geom_a = shape(geometry_a)
    geom_b = shape(geometry_b)

    operations: dict[str, Any] = {
        "intersection": geom_a.intersection,
        "union": geom_a.union,
        "difference": geom_a.difference,
        "symmetric_difference": geom_a.symmetric_difference,
    }

    fn = operations.get(operation)
    if fn is None:
        raise ValueError(f"Unknown operation: {operation}. Valid: {list(operations.keys())}")

    result_geom = fn(geom_b)
    return {"geometry": mapping(result_geom), "operation": operation}


async def coordinate_transform(
    geometry: dict[str, Any],
    source_crs: str = "EPSG:4326",
    target_crs: str = "EPSG:4490",
) -> dict[str, Any]:
    from pyproj import Transformer
    from shapely.ops import transform

    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    geom = shape(geometry)
    transformed = transform(transformer.transform, geom)
    return {"geometry": mapping(transformed), "source_crs": source_crs, "target_crs": target_crs}


async def geometry_properties(geometry: dict[str, Any]) -> dict[str, Any]:
    geom = shape(geometry)
    props: dict[str, Any] = {
        "geometry_type": geom.geom_type,
        "is_valid": geom.is_valid,
        "bounds": list(geom.bounds),
        "centroid": mapping(geom.centroid),
    }
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        props["area"] = geom.area
        props["perimeter"] = geom.length
    elif geom.geom_type in ("LineString", "MultiLineString"):
        props["length"] = geom.length
    elif geom.geom_type in ("Point", "MultiPoint"):
        props["coordinate_count"] = len(geom.coords) if geom.geom_type == "Point" else len(geom.geoms)
    return props
