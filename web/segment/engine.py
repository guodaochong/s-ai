import numpy as np
import logging
from pathlib import Path
from segment_anything import sam_model_registry, SamAutomaticMaskGenerator

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models"
MODEL_PATH = MODEL_DIR / "sam_vit_b_01ec64.pth"
_sam = None
_mask_gen = None


def _load_model():
    global _sam, _mask_gen
    if _mask_gen is not None:
        return _mask_gen
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"SAM model not found at {MODEL_PATH}. Download sam_vit_b_01ec64.pth first.")
    logger.info("[SAM] Loading vit_b model...")
    _sam = sam_model_registry["vit_b"](checkpoint=str(MODEL_PATH))
    _sam.to("cuda:0")
    _mask_gen = SamAutomaticMaskGenerator(
        _sam,
        points_per_side=32,
        pred_iou_thresh=0.88,
        stability_score_thresh=0.93,
        min_mask_region_area=100,
    )
    logger.info("[SAM] Model loaded on CUDA")
    return _mask_gen


def _mask_to_polygon(mask: np.ndarray) -> list[tuple[int, int]]:
    import cv2
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return []
    largest = max(contours, key=cv2.contourArea)
    epsilon = 0.01 * cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, epsilon, True)
    if len(approx) < 3:
        return []
    return [(int(p[0][0]), int(p[0][1])) for p in approx]


def _is_building_like(area_m2: float, aspect: float, solidity: float) -> bool:
    if area_m2 < 30 or area_m2 > 4000:
        return False
    if aspect > 5:
        return False
    if solidity < 0.5:
        return False
    return True


def _classify_building(area_m2: float, height_m: int, aspect: float, solidity: float) -> dict:
    if area_m2 < 80 and height_m <= 6:
        return {"type": "附属设施", "icon": "🔧", "color": "#94a3b8"}
    if area_m2 > 1500 and (aspect > 2.5 or height_m <= 9):
        return {"type": "工业仓储", "icon": "🏭", "color": "#f59e0b"}
    if area_m2 > 1200 and solidity < 0.65:
        return {"type": "公共设施", "icon": "🏫", "color": "#a78bfa"}
    if area_m2 < 300 and height_m <= 9:
        return {"type": "低层住宅", "icon": "🏠", "color": "#4ade80"}
    if area_m2 < 800 and height_m >= 12:
        return {"type": "高层住宅", "icon": "🏢", "color": "#60a5fa"}
    if area_m2 >= 500 and height_m >= 12:
        return {"type": "商业办公", "icon": "🏬", "color": "#22d3ee"}
    return {"type": "一般建筑", "icon": "🏢", "color": "#64748b"}


def segment_buildings(image: np.ndarray, bbox: list[float]) -> dict:
    import cv2
    from .tile_fetcher import pixel_to_lonlat

    mask_gen = _load_model()
    orig_h, orig_w = image.shape[:2]

    if image.shape[2] == 4:
        image = image[:, :, :3]

    max_dim = 1280
    scale = 1.0
    if max(orig_w, orig_h) > max_dim:
        scale = max_dim / max(orig_w, orig_h)
        new_w, new_h = int(orig_w * scale), int(orig_h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        logger.info(f"[SAM] Resized {orig_w}x{orig_h} -> {new_w}x{new_h} (scale={scale:.3f})")
    else:
        image = image.copy()

    h, w = image.shape[:2]
    logger.info(f"[SAM] Generating masks for {w}x{h} image...")
    masks = mask_gen.generate(image)
    logger.info(f"[SAM] Generated {len(masks)} raw masks")

    buildings = []
    for m in masks:
        seg = m["segmentation"]
        area_px = m["area"]
        area_m2 = _pixel_area_to_m2(area_px, bbox, w, h)

        x, y, bw, bh = cv2.boundingRect(seg.astype(np.uint8))
        aspect = max(bw, bh) / max(min(bw, bh), 1)
        contours, _ = cv2.findContours(seg.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour_area = cv2.contourArea(max(contours, key=cv2.contourArea)) if contours else 0
        solidity = area_px / max(contour_area, 1)

        if not _is_building_like(area_m2, aspect, solidity):
            continue

        polygon_px = _mask_to_polygon(seg)
        if len(polygon_px) < 3:
            continue

        coords = []
        for px, py in polygon_px:
            lat, lon = pixel_to_lonlat(px, py, w, h, bbox)
            coords.append([round(lon, 7), round(lat, 7)])

        area_m2 = _pixel_area_to_m2(area_px, bbox, w, h)
        est_height = _estimate_height(area_m2)
        btype = _classify_building(area_m2, est_height, aspect, solidity)

        cx_px = x + bw // 2
        cy_px = y + bh // 2
        center_lat, center_lon = pixel_to_lonlat(cx_px, cy_px, w, h, bbox)

        buildings.append({
            "polygon": coords,
            "center": [round(center_lon, 7), round(center_lat, 7)],
            "area_m2": round(area_m2, 1),
            "est_height_m": est_height,
            "footprint_w_m": round(_pixels_to_m(bw, bbox, w, h, "x"), 1),
            "footprint_h_m": round(_pixels_to_m(bh, bbox, w, h, "y"), 1),
            "confidence": round(m.get("predicted_iou", 0.9), 3),
            "building_type": btype["type"],
            "type_icon": btype["icon"],
            "type_color": btype["color"],
        })

    logger.info(f"[SAM] Filtered to {len(buildings)} building-like shapes")

    features = []
    for b in buildings:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [b["polygon"] + [b["polygon"][0]]]},
            "properties": {
                "height_m": b["est_height_m"],
                "area_m2": b["area_m2"],
                "width_m": b["footprint_w_m"],
                "length_m": b["footprint_h_m"],
                "confidence": b["confidence"],
                "center": b["center"],
                "building_type": b["building_type"],
                "type_icon": b["type_icon"],
                "type_color": b["type_color"],
            },
        })

    avg_h = sum(b["est_height_m"] for b in buildings) / max(len(buildings), 1)
    return {
        "buildings": features,
        "count": len(features),
        "avg_height_m": round(avg_h, 1),
        "total_area_m2": round(sum(b["area_m2"] for b in buildings), 1),
        "bbox": bbox,
        "image_size": [w, h],
    }


def _pixel_area_to_m2(pixel_area: float, bbox: list[float], w: int, h: int) -> float:
    import math
    lat_mid = (bbox[1] + bbox[3]) / 2
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_mid))
    deg_per_px_x = (bbox[2] - bbox[0]) / w
    deg_per_px_y = (bbox[3] - bbox[1]) / h
    m_per_px_x = deg_per_px_x * m_per_deg_lon
    m_per_px_y = deg_per_px_y * m_per_deg_lat
    return pixel_area * m_per_px_x * m_per_px_y


def _pixels_to_m(pixels: float, bbox: list[float], w: int, h: int, axis: str) -> float:
    import math
    lat_mid = (bbox[1] + bbox[3]) / 2
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_mid))
    if axis == "x":
        return pixels * (bbox[2] - bbox[0]) / w * m_per_deg_lon
    else:
        return pixels * (bbox[3] - bbox[1]) / h * m_per_deg_lat


def _estimate_height(area_m2: float) -> int:
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
    if area_m2 < 5000:
        return 20
    return 30
