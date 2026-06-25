"""SAM + GLM-4V aerial image segmentation engine.

SAM (Segment Anything) auto-segments an image into regions, then
GLM-4V identifies each region's land-cover type and condition.
Zero-shot — no training data required.

Pipeline:
1. SamAutomaticMaskGenerator → N region masks
2. Filter top-K by area, discard tiny fragments
3. Render coloured overlays on each region (distinct colour + number)
4. Single GLM-4V call: "identify each numbered coloured region"
5. Return annotated image + per-region classification

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import base64
import io
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import structlog

from app.config import logger

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

logger = structlog.get_logger()

_SAM_MODEL = None
_SAM_MASK_GEN = None
_SAM_CHECKPOINT = Path(__file__).parent.parent / "segment" / "models" / "sam_vit_b_01ec64.pth"

_REGION_COLORS = [
    (0, 0, 255), (0, 255, 0), (255, 0, 0), (0, 255, 255),
    (255, 0, 255), (255, 255, 0), (128, 0, 255), (0, 128, 255),
    (255, 128, 0), (128, 255, 0), (255, 0, 128), (0, 255, 128),
    (200, 200, 0), (0, 200, 200), (200, 0, 200),
]


def _get_sam():
    global _SAM_MODEL, _SAM_MASK_GEN
    if _SAM_MASK_GEN is not None:
        return _SAM_MASK_GEN

    from segment_anything import sam_model_registry, SamAutomaticMaskGenerator
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_type = "vit_b"

    if not _SAM_CHECKPOINT.exists():
        logger.error("[SAM] checkpoint not found", path=str(_SAM_CHECKPOINT))
        return None

    _SAM_MODEL = sam_model_registry[model_type](checkpoint=str(_SAM_CHECKPOINT))
    _SAM_MODEL.to(device)

    _SAM_MASK_GEN = SamAutomaticMaskGenerator(
        _SAM_MODEL,
        pred_iou_thresh=0.86,
        stability_score_thresh=0.92,
        min_mask_region_area=800,
    )
    logger.info("[SAM] model loaded", device=device, type=model_type)
    return _SAM_MASK_GEN


def _filter_masks(masks: list[dict], max_regions: int = 12) -> list[dict]:
    sorted_masks = sorted(masks, key=lambda m: m["area"], reverse=True)
    total_pixels = masks[0]["segmentation"].size if masks else 1
    significant = [m for m in sorted_masks if m["area"] > total_pixels * 0.005]
    return significant[:max_regions]


def _render_overlays(image: np.ndarray, masks: list[dict]) -> np.ndarray:
    annotated = image.copy()
    for i, m in enumerate(masks):
        seg = m["segmentation"]
        color = _REGION_COLORS[i % len(_REGION_COLORS)]

        overlay = annotated.copy()
        overlay[seg] = color
        annotated = cv2.addWeighted(annotated, 0.55, overlay, 0.45, 0)

        ys, xs = np.where(seg)
        if len(ys) > 0:
            cx, cy = int(np.mean(xs)), int(np.mean(ys))
            cv2.circle(annotated, (cx, cy), 12, (0, 0, 0), -1)
            cv2.circle(annotated, (cx, cy), 12, color, 2)
            cv2.putText(annotated, str(i + 1), (cx - 5, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    return annotated


_SEGMENT_PROMPT = """分析这张航拍/无人机照片。图中有多个编号的彩色标注区域。

请识别每个编号区域的地物类型和状态。返回JSON：
{"regions":[{"id":1,"type":"水体/建筑/道路/植被/车辆/裸地/其他","status":"正常/受淹/损坏/无","description":"简短描述(10-20字)"}],"summary":"整体场景描述(20-30字)"}"""


async def segment_and_analyze(image_b64: str, user_context: str = "") -> dict[str, Any]:
    mask_gen = _get_sam()
    if mask_gen is None:
        return {"error": "SAM模型未加载"}

    img_bytes = base64.b64decode(image_b64)
    img_array = np.frombuffer(img_bytes, np.uint8)
    image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if image is None:
        return {"error": "无法解码图片"}

    if image.shape[1] > 1280:
        scale = 1280 / image.shape[1]
        image = cv2.resize(image, None, fx=scale, fy=scale)

    t0 = time.time()
    logger.info("[SAM] generating masks", shape=image.shape)

    masks = mask_gen.generate(image)
    logger.info("[SAM] masks generated", count=len(masks), elapsed_ms=int((time.time() - t0) * 1000))

    if not masks:
        return {"error": "未检测到任何区域", "annotated_b64": ""}

    filtered = _filter_masks(masks)
    logger.info("[SAM] filtered regions", before=len(masks), after=len(filtered))

    annotated = _render_overlays(image, filtered)

    _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
    annotated_b64 = base64.b64encode(buf).decode()

    from app.config import MODEL_VISION
    from app.llm import call_llm
    import re, json

    glmv_b64 = annotated_b64
    if len(glmv_b64) > 80000:
        small = cv2.resize(annotated, None, fx=0.6, fy=0.6)
        _, sbuf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
        glmv_b64 = base64.b64encode(sbuf).decode()

    prompt = _SEGMENT_PROMPT
    if user_context:
        prompt += f"\n用户补充：{user_context[:150]}"

    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{glmv_b64}"}},
    ]}]

    regions: list[dict] = []
    summary = ""
    try:
        content, _, _ = await call_llm(
            messages, model=MODEL_VISION, use_tools=False, max_tokens_override=1024,
        )
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            data = json.loads(match.group())
            regions = data.get("regions", [])
            summary = data.get("summary", "")
    except Exception as e:
        logger.error("[SAM] GLM-4V analysis failed", error=str(e)[:200])
        summary = f"分析失败: {str(e)[:80]}"

    region_colors = []
    for i in range(len(filtered)):
        c = _REGION_COLORS[i % len(_REGION_COLORS)]
        region_colors.append({"r": c[2], "g": c[1], "b": c[0]})

    return {
        "annotated_b64": annotated_b64,
        "regions": regions,
        "summary": summary,
        "region_count": len(filtered),
        "total_masks": len(masks),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "region_colors": region_colors,
    }
