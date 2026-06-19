import logging
import numpy as np
import cv2
import httpx
import asyncio
import rasterio
from rasterio.windows import from_bounds, Window
from pyproj import Transformer

logger = logging.getLogger(__name__)

STAC_URL = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items"

_UTM_CACHE: dict[str, Transformer] = {}


def _get_transformer(utm_epsg: str) -> Transformer:
    if utm_epsg not in _UTM_CACHE:
        _UTM_CACHE[utm_epsg] = Transformer.from_crs("EPSG:4326", utm_epsg, always_xy=True)
    return _UTM_CACHE[utm_epsg]


def _lonlat_to_utm_zone(lon: float) -> str:
    zone = int((lon + 180) / 6) + 1
    return f"EPSG:326{zone:02d}"


async def search_scenes(
    bbox_wgs84: list[float],
    date_start: str = "2024-06-01",
    date_end: str = "2024-10-31",
    max_cloud: float = 20.0,
    limit: int = 30,
) -> list[dict]:
    bbox_str = ",".join(str(v) for v in bbox_wgs84)
    datetime_str = f"{date_start}T00:00:00Z/{date_end}T00:00:00Z"
    params = {"bbox": bbox_str, "datetime": datetime_str, "limit": limit}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(STAC_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    covering = []
    for f in features:
        sb = f["bbox"]
        if not (sb[0] <= bbox_wgs84[0] and sb[2] >= bbox_wgs84[2] and
                sb[1] <= bbox_wgs84[1] and sb[3] >= bbox_wgs84[3]):
            continue
        cloud = f["properties"].get("eo:cloud_cover", 999)
        if cloud > max_cloud:
            continue
        assets = f.get("assets", {})
        green = assets.get("green", {}).get("href")
        nir = assets.get("nir", {}).get("href")
        swir1 = assets.get("swir16", {}).get("href") or assets.get("swir1", {}).get("href")
        visual = assets.get("visual", {}).get("href")
        if not green or not nir:
            continue
        covering.append({
            "date": f["properties"]["datetime"][:10],
            "cloud": cloud,
            "green": green,
            "nir": nir,
            "swir1": swir1,
            "visual": visual,
            "scene_id": f.get("id", ""),
        })
    covering.sort(key=lambda x: x["cloud"])
    return covering


def _read_band_window(url: str, bbox_utm: list[float]) -> tuple[np.ndarray, object]:
    with rasterio.open(url) as ds:
        fwin = from_bounds(*bbox_utm, ds.transform)
        win = Window(int(fwin.col_off), int(fwin.row_off), int(fwin.width), int(fwin.height))
        data = ds.read(1, window=win)
        transform = ds.window_transform(win)
    return data, transform


def _pixel_to_lonlat(row: int, col: int, transform, utm_epsg: str) -> tuple[float, float]:
    import math
    px_x = transform.c + col * transform.a
    px_y = transform.f + row * transform.e
    inv = _get_transformer(utm_epsg).transform
    lon, lat = inv(px_x, px_y, direction="INVERSE")
    return lat, lon


def _otsu_threshold(data: np.ndarray, valid_mask: np.ndarray) -> float:
    valid = data[valid_mask]
    if len(valid) < 100:
        return 0.0
    hist, edges = np.histogram(valid, bins=256)
    centers = (edges[:-1] + edges[1:]) / 2
    total = len(valid)
    w1 = np.cumsum(hist)
    w2 = total - w1
    m1 = np.cumsum(hist * centers) / (w1 + 1e-10)
    m2 = (np.sum(hist * centers) - np.cumsum(hist * centers)) / (w2 + 1e-10)
    between = w1 * w2 * (m1 - m2) ** 2
    return float(centers[np.argmax(between)])


def extract_water(
    bbox_wgs84: list[float],
    scene: dict,
    ndwi_threshold: float = 0.0,
    min_area_px: int = 50,
) -> dict:
    from scipy import ndimage

    lon_mid = (bbox_wgs84[0] + bbox_wgs84[2]) / 2
    utm_epsg = _lonlat_to_utm_zone(lon_mid)
    transformer = _get_transformer(utm_epsg)
    x1, y1 = transformer.transform(bbox_wgs84[0], bbox_wgs84[1])
    x2, y2 = transformer.transform(bbox_wgs84[2], bbox_wgs84[3])
    bbox_utm = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]

    green_data, green_transform = _read_band_window(scene["green"], bbox_utm)
    nir_data, _ = _read_band_window(scene["nir"], bbox_utm)

    h = min(green_data.shape[0], nir_data.shape[0])
    w = min(green_data.shape[1], nir_data.shape[1])
    green_f = green_data[:h, :w].astype(np.float32)
    nir_f = nir_data[:h, :w].astype(np.float32)

    swir1_url = scene.get("swir1")
    if swir1_url:
        try:
            swir_data, _ = _read_band_window(swir1_url, bbox_utm)
            swir_f = swir_data[:h, :w].astype(np.float32)
            wi = (green_f - swir_f) / (green_f + swir_f + 1e-10)
            wi_method = "MNDWI"
            logger.info("[water] Using MNDWI (Green-SWIR1)")
        except Exception:
            wi = (green_f - nir_f) / (green_f + nir_f + 1e-10)
            wi_method = "NDWI"
    else:
        wi = (green_f - nir_f) / (green_f + nir_f + 1e-10)
        wi_method = "NDWI"

    valid_mask = np.isfinite(wi)
    otsu_t = _otsu_threshold(wi, valid_mask)
    threshold = max(otsu_t, ndwi_threshold)
    logger.info(f"[water] {wi_method} Otsu threshold={otsu_t:.3f}, using={threshold:.3f}")

    water_mask = wi > threshold
    water_mask = ndimage.binary_closing(water_mask, structure=np.ones((5, 5)))
    water_mask = ndimage.binary_closing(water_mask, structure=np.ones((3, 3)))
    water_mask = ndimage.binary_opening(water_mask, structure=np.ones((3, 3)))
    water_mask = ndimage.binary_fill_holes(water_mask)

    water_u8 = (water_mask.astype(np.uint8) * 255)
    contours, _ = cv2.findContours(water_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    pixel_area_m2 = 100.0

    features = []
    for c in contours:
        area_px = cv2.contourArea(c)
        if area_px < min_area_px:
            continue
        epsilon = 0.005 * cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, epsilon, True)
        if len(approx) < 3:
            continue
        coords = []
        for pt in approx:
            lat, lon = _pixel_to_lonlat(int(pt[0][1]), int(pt[0][0]), green_transform, utm_epsg)
            coords.append([round(lon, 7), round(lat, 7)])
        coords.append(coords[0])

        M = cv2.moments(c)
        if M["m00"] > 0:
            cx_px = int(M["m10"] / M["m00"])
            cy_px = int(M["m01"] / M["m00"])
            center_lat, center_lon = _pixel_to_lonlat(cy_px, cx_px, green_transform, utm_epsg)
        else:
            center_lat, center_lon = coords[0][1], coords[0][0]

        x, y, bw, bh = cv2.boundingRect(c)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "area_m2": round(area_px * pixel_area_m2, 1),
                "width_m": round(bw * 10, 1),
                "length_m": round(bh * 10, 1),
                "center": [round(center_lon, 7), round(center_lat, 7)],
                "ndwi_mean": round(float(ndwi[y:y+bh, x:x+bw].mean()), 3),
            },
        })

    total_water_px = int((ndwi > ndwi_threshold).sum())
    total_area_m2 = round(total_water_px * pixel_area_m2, 1)
    bbox_area_m2 = round(h * w * pixel_area_m2, 1)
    water_ratio = total_area_m2 / max(bbox_area_m2, 1) * 100

    return {
        "date": scene["date"],
        "cloud_cover": round(scene["cloud"], 2),
        "scene_id": scene["scene_id"],
        "ndwi_range": [round(float(ndwi.min()), 3), round(float(ndwi.max()), 3)],
        "water_bodies": features,
        "water_body_count": len(features),
        "total_water_area_m2": total_area_m2,
        "total_water_area_km2": round(total_area_m2 / 1e6, 4),
        "bbox_area_km2": round(bbox_area_m2 / 1e6, 2),
        "water_coverage_pct": round(water_ratio, 2),
        "bbox": bbox_wgs84,
        "image_size": [w, h],
    }


def render_ndwi_preview(ndwi_data: np.ndarray, max_dim: int = 512) -> bytes:
    import io
    h, w = ndwi_data.shape
    scale = min(1.0, max_dim / max(h, w))
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    ndwi_small = cv2.resize(ndwi_data, (new_w, new_h), interpolation=cv2.INTER_AREA)

    cmap = np.zeros((new_h, new_w, 3), dtype=np.uint8)
    cmap[ndwi_small > 0.3] = [0, 40, 180]
    cmap[(ndwi_small > 0.1) & (ndwi_small <= 0.3)] = [0, 90, 210]
    cmap[(ndwi_small > 0.0) & (ndwi_small <= 0.1)] = [40, 140, 240]
    cmap[(ndwi_small > -0.2) & (ndwi_small <= 0.0)] = [80, 160, 90]
    cmap[(ndwi_small > -0.5) & (ndwi_small <= -0.2)] = [140, 180, 70]
    cmap[ndwi_small <= -0.5] = [200, 200, 200]

    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(cmap).save(buf, format="PNG")
    return buf.getvalue()


def detect_water_change(
    bbox_wgs84: list[float],
    scene1: dict,
    scene2: dict,
    ndwi_threshold: float = 0.0,
    min_area_px: int = 30,
) -> dict:
    lon_mid = (bbox_wgs84[0] + bbox_wgs84[2]) / 2
    utm_epsg = _lonlat_to_utm_zone(lon_mid)
    transformer = _get_transformer(utm_epsg)
    x1, y1 = transformer.transform(bbox_wgs84[0], bbox_wgs84[1])
    x2, y2 = transformer.transform(bbox_wgs84[2], bbox_wgs84[3])
    bbox_utm = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]

    g1, t1 = _read_band_window(scene1["green"], bbox_utm)
    n1, _ = _read_band_window(scene1["nir"], bbox_utm)
    g2, t2 = _read_band_window(scene2["green"], bbox_utm)
    n2, _ = _read_band_window(scene2["nir"], bbox_utm)

    h = min(g1.shape[0], n1.shape[0], g2.shape[0], n2.shape[0])
    w = min(g1.shape[1], n1.shape[1], g2.shape[1], n2.shape[1])

    ndwi1 = (g1[:h, :w].astype(np.float32) - n1[:h, :w].astype(np.float32)) / (g1[:h, :w].astype(np.float32) + n1[:h, :w].astype(np.float32) + 1e-10)
    ndwi2 = (g2[:h, :w].astype(np.float32) - n2[:h, :w].astype(np.float32)) / (g2[:h, :w].astype(np.float32) + n2[:h, :w].astype(np.float32) + 1e-10)

    mask1 = ndwi1 > ndwi_threshold
    mask2 = ndwi2 > ndwi_threshold

    expanded = mask2 & ~mask1
    shrunk = mask1 & ~mask2
    stable = mask1 & mask2

    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    expanded_m = cv2.morphologyEx(expanded.astype(np.uint8), cv2.MORPH_CLOSE, kern)
    shrunk_m = cv2.morphologyEx(shrunk.astype(np.uint8), cv2.MORPH_CLOSE, kern)

    pixel_area_m2 = 100.0
    area1_m2 = int(mask1.sum() * pixel_area_m2)
    area2_m2 = int(mask2.sum() * pixel_area_m2)
    expanded_m2 = int(expanded.sum() * pixel_area_m2)
    shrunk_m2 = int(shrunk.sum() * pixel_area_m2)
    stable_m2 = int(stable.sum() * pixel_area_m2)

    def mask_to_features(mask: np.ndarray, change_type: str, transform, epsg: str) -> list[dict]:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        feats = []
        for c in contours:
            if cv2.contourArea(c) < min_area_px:
                continue
            epsilon = 0.005 * cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, epsilon, True)
            if len(approx) < 3:
                continue
            coords = []
            for pt in approx:
                lat, lon = _pixel_to_lonlat(int(pt[0][1]), int(pt[0][0]), transform, epsg)
                coords.append([round(lon, 6), round(lat, 6)])
            coords.append(coords[0])
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {
                    "change": change_type,
                    "area_m2": round(cv2.contourArea(c) * pixel_area_m2, 1),
                },
            })
        return feats

    expanded_feats = mask_to_features(expanded_m, "expanded", t2, utm_epsg)
    shrunk_feats = mask_to_features(shrunk_m, "shrunk", t1, utm_epsg)

    change_pct = ((area2_m2 - area1_m2) / max(area1_m2, 1)) * 100

    return {
        "water_change": True,
        "date1": scene1["date"],
        "date2": scene2["date"],
        "cloud1": round(scene1["cloud"], 1),
        "cloud2": round(scene2["cloud"], 1),
        "area1_m2": area1_m2,
        "area2_m2": area2_m2,
        "area1_km2": round(area1_m2 / 1e6, 4),
        "area2_km2": round(area2_m2 / 1e6, 4),
        "expanded_m2": expanded_m2,
        "shrunk_m2": shrunk_m2,
        "stable_m2": stable_m2,
        "change_pct": round(change_pct, 1),
        "expanded_features": expanded_feats,
        "shrunk_features": shrunk_feats,
        "bbox": bbox_wgs84,
        "data_source": "Sentinel-2 L2A multi-temporal NDWI change detection",
    }
