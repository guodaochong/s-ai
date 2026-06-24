"""Video analysis engine — OpenCV water detection + GLM-4V assessment.

Extracts frames from uploaded video at regular intervals, detects water
regions via HSV colour segmentation, tracks water-area changes over
time, and optionally calls GLM-4V for deep scene understanding on key
frames.

Designed for flood / river / reservoir monitoring footage from drones,
CCTV, or phone cameras.  No PyTorch dependency — pure OpenCV + numpy.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import cv2
import numpy as np
import structlog

from app.config import logger
from app.multimodal import _resize_image_b64
from app.utils import sse

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

logger = structlog.get_logger()


_HSV_LOWER = np.array([95, 60, 50])
_HSV_UPPER = np.array([130, 255, 220])

_MIN_AREA_RATIO = 0.01

_YOLO_MODEL = None
_WATER_CLASSES = {0: "person", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 8: "boat"}


def _get_yolo():
    global _YOLO_MODEL
    if _YOLO_MODEL is not None:
        return _YOLO_MODEL
    try:
        from ultralytics import YOLO
        _YOLO_MODEL = YOLO("yolov8n.pt")
        logger.info("[Video] YOLOv8n loaded on GPU")
        return _YOLO_MODEL
    except Exception as e:
        logger.warning("[Video] YOLO unavailable, HSV-only mode", error=str(e)[:100])
        return None


def _yolo_detect(frame: np.ndarray) -> list[dict]:
    model = _get_yolo()
    if model is None:
        return []
    results = model(frame, verbose=False, conf=0.4)
    dets: list[dict] = []
    for r in results:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            if cls_id not in _WATER_CLASSES:
                continue
            x1, y1, x2, y2 = [round(float(v)) for v in box.xyxy[0]]
            dets.append({
                "class": _WATER_CLASSES[cls_id],
                "confidence": round(float(box.conf[0]), 2),
                "bbox": [x1, y1, x2, y2],
            })
    return dets


@dataclass
class FrameResult:
    timestamp: float
    frame_idx: int
    water_ratio: float
    water_changed: float
    annotated_b64: str
    contours_count: int
    dominant_hue: float
    detections: list[dict] = field(default_factory=list)
    glmv: dict = field(default_factory=dict)


@dataclass
class VideoAnalysisResult:
    duration_s: float
    fps: float
    total_frames: int
    analyzed_frames: list[FrameResult] = field(default_factory=list)
    max_water_ratio: float = 0.0
    water_trend: str = "stable"
    glmv_summary: str = ""
    glmv_assessment: dict[str, Any] = field(default_factory=dict)


def _detect_water(hsv: np.ndarray) -> tuple[np.ndarray, float]:
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in _HSV_RANGES:
        mask |= cv2.inRange(hsv, lower, upper)
    kernel = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    cleaned = np.zeros_like(mask)
    min_pix = int(mask.size * _MIN_AREA_RATIO)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        if area < min_pix:
            continue
        if w > 0 and h > 0 and max(w, h) / min(w, h) > 8:
            continue
        cleaned[labels == i] = 255

    mask = cleaned
    ratio = float(np.count_nonzero(mask)) / mask.size
    return mask, ratio


def _annotate_frame(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    overlay = frame.copy()
    overlay[mask > 0] = [0, 200, 255]
    return cv2.addWeighted(frame, 0.6, overlay, 0.4, 0)


def _frame_to_b64(frame: np.ndarray, quality: int = 70) -> str:
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf).decode()


_FONT_CACHE: dict[int, Any] = {}


def _get_font(size: int = 22) -> Any:
    from PIL import ImageFont
    if size not in _FONT_CACHE:
        for path in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
            if Path(path).exists():
                _FONT_CACHE[size] = ImageFont.truetype(path, size)
                break
        else:
            _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def _draw_text_cn(img: np.ndarray, text: str, pos: tuple[int, int], color=(255, 255, 0), size: int = 22) -> np.ndarray:
    from PIL import Image, ImageDraw
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    rgb = (color[2], color[1], color[0]) if len(color) == 3 else color
    draw.text(pos, text, font=_get_font(size), fill=rgb)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


_HSV_RANGES = [
    (np.array([95, 50, 40]), np.array([130, 255, 220])),
    (np.array([35, 40, 30]), np.array([85, 255, 200])),
    (np.array([10, 40, 20]), np.array([30, 200, 150])),
]


def extract_frames(video_path: str | Path, interval_s: float = 3.0) -> list[tuple[int, float, np.ndarray]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(fps * interval_s))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    frames: list[tuple[int, float, np.ndarray]] = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % step == 0:
            ts = idx / fps
            if frame.shape[1] > 1280:
                scale = 1280 / frame.shape[1]
                frame = cv2.resize(frame, None, fx=scale, fy=scale)
            frames.append((idx, ts, frame))
        idx += 1
    cap.release()
    return frames


_FRAME_ANALYSIS_PROMPT = """分析这个视频帧画面。识别水体并评估。

返回JSON：{"water_type":"河流/湖泊/水库/洪水/排水渠/无水体","water_state":"平静/流动/湍急/溢流","water_ratio":0.0-1.0,"objects_in_water":["人","车辆","船只","漂浮物"],"environment":"城市/农田/山地/荒野","hazards":[],"risk_level":1-5,"summary":"一句话"}"""


async def analyze_frame_glmv(frame: np.ndarray, ts: float) -> dict[str, Any]:
    from app.config import MODEL_VISION
    from app.llm import call_llm
    import re, json

    b64 = _resize_image_b64(_frame_to_b64(frame, quality=70))
    messages = [{"role": "user", "content": [
        {"type": "text", "text": _FRAME_ANALYSIS_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]}]
    try:
        content, _, _ = await call_llm(
            messages, model=MODEL_VISION, use_tools=False, max_tokens_override=800,
        )
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.warning("[Video] GLM-4V frame analysis failed", ts=ts, error=str(e)[:100])
    return {"water_ratio": 0.0, "water_type": "未知", "summary": "分析失败"}


async def analyze_frames_async(frames: list[tuple[int, float, np.ndarray]]) -> list[FrameResult]:
    results: list[FrameResult] = []
    prev_ratio = 0.0
    yolo = _get_yolo()

    for fidx, ts, frame in frames:
        glmv = await analyze_frame_glmv(frame, ts)
        ratio = float(glmv.get("water_ratio", 0))
        changed = ratio - prev_ratio
        has_water = ratio > 0.01 and glmv.get("water_type", "无") != "无水体"

        annotated = frame.copy()
        if frame.shape[1] > 1280:
            scale = 1280 / frame.shape[1]
            annotated = cv2.resize(annotated, None, fx=scale, fy=scale)

        if has_water:
            hsv = cv2.cvtColor(annotated, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, _HSV_LOWER, _HSV_UPPER)
            kernel = np.ones((7, 7), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
            overlay = annotated.copy()
            overlay[mask > 0] = [0, 200, 255]
            annotated = cv2.addWeighted(annotated, 0.6, overlay, 0.4, 0)

        wa = glmv.get("water_type", "")
        ws = glmv.get("water_state", "")
        wr = int(ratio * 100)
        cv2.rectangle(annotated, (0, 0), (annotated.shape[1], 40), (0, 0, 0), -1)
        annotated = _draw_text_cn(annotated, f"{wa} {ws} {wr}%", (10, 8), color=(0, 255, 255), size=22)

        detections: list[dict] = []
        if yolo is not None:
            detections = _yolo_detect(frame)
            for d in detections:
                x1, y1, x2, y2 = d["bbox"]
                color = (0, 0, 255) if d["class"] == "person" else (255, 100, 0)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                annotated = _draw_text_cn(annotated, f'{d["class"]} {d["confidence"]:.0%}', (x1, y1 - 22), color=color, size=16)

        results.append(FrameResult(
            timestamp=round(ts, 1),
            frame_idx=fidx,
            water_ratio=round(ratio, 4),
            water_changed=round(changed, 4),
            annotated_b64=_frame_to_b64(annotated),
            contours_count=0,
            dominant_hue=0.0,
            detections=detections,
            glmv=glmv,
        ))
        prev_ratio = ratio

    return results


async def glmv_video_assess(
    frames: list[tuple[int, float, np.ndarray]],
    user_context: str = "",
) -> dict[str, Any]:
    from app.multimodal import _DISASTER_PROMPT
    from app.config import MODEL_VISION
    from app.llm import call_llm
    import re, json

    if not frames:
        return {}

    key_indices: list[int] = []
    if len(frames) >= 3:
        key_indices = [0, len(frames) // 2, len(frames) - 1]
    else:
        key_indices = list(range(len(frames)))

    summaries: list[str] = []
    assessment: dict[str, Any] = {}

    for ki in key_indices:
        _, ts, frame = frames[ki]
        b64 = _frame_to_b64(frame, quality=75)
        b64 = _resize_image_b64(b64)

        prompt = (
            "分析这段水务监控视频的第" + str(round(ts, 1)) + "秒画面。"
            "识别：水体类型(河流/水库/洪水/内涝)、水面状态(平静/湍流/溢流)、"
            "周边环境(建筑/道路/农田)、是否有人员或车辆在水中、安全隐患。"
            "返回JSON：{\"scene\":\"\",\"water_type\":\"\",\"water_state\":\"\",\"environment\":\"\",\"objects_in_water\":[],\"hazards\":[],\"risk_level\":1-5,\"summary\":\"\"}"
        )
        if user_context:
            prompt += "\n用户补充：" + user_context[:150]

        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}]
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
                summaries.append(f"[{round(ts,1)}s] {data.get('summary', '')}")
                if not assessment or data.get("risk_level", 0) > assessment.get("risk_level", 0):
                    assessment = data
        except Exception as e:
            logger.warning("[Video] GLM-4V frame analysis failed", frame_idx=ki, error=str(e)[:100])

    return {
        "summary": " | ".join(summaries) if summaries else "分析完成",
        "assessment": assessment,
    }


def _compute_trend(results: list[FrameResult]) -> tuple[str, float]:
    if len(results) < 2:
        return "stable", 0.0
    first = results[0].water_ratio
    last = results[-1].water_ratio
    delta = last - first
    if delta > 0.02:
        return "rising", delta
    if delta < -0.02:
        return "falling", delta
    return "stable", delta


async def analyze_video(
    video_path: str | Path,
    interval_s: float = 3.0,
    use_glmv: bool = True,
    user_context: str = "",
) -> AsyncIterator[dict]:
    video_path = Path(video_path)
    t0 = time.time()

    yield sse({"type": "video_analysis_start", "filename": video_path.name})

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        yield sse({"type": "video_analysis_error", "error": "无法打开视频文件"})
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / fps if fps > 0 else 0
    cap.release()

    yield sse({
        "type": "video_info",
        "duration_s": round(duration, 1),
        "fps": round(fps, 1),
        "total_frames": total,
    })

    yield sse({"type": "thinking", "agent": "video", "content": "🎬 正在提取视频帧..."})
    frames = extract_frames(video_path, interval_s)
    yield sse({"type": "thinking", "agent": "video", "content": f"✅ 提取了{len(frames)}帧 (每{interval_s}秒一帧)"})

    if not frames:
        yield sse({"type": "video_analysis_error", "error": "无法提取视频帧"})
        return

    yield sse({"type": "thinking", "agent": "video", "content": "🧠 GLM-4V + YOLOv8 逐帧分析中..."})
    results = await analyze_frames_async(frames)

    best_assessment: dict[str, Any] = {}
    for i, r in enumerate(results):
        if r.glmv and r.glmv.get("risk_level", 0) > best_assessment.get("risk_level", 0):
            best_assessment = r.glmv
        yield sse({
            "type": "video_frame_result",
            "frame_idx": i,
            "total": len(results),
            "timestamp": r.timestamp,
            "water_ratio": r.water_ratio,
            "water_changed": r.water_changed,
            "contours_count": r.contours_count,
            "frame_b64": r.annotated_b64,
            "detections": r.detections,
            "glmv": r.glmv,
        })

    trend, delta = _compute_trend(results)
    max_ratio = max((r.water_ratio for r in results), default=0.0)

    yield sse({
        "type": "video_stats",
        "max_water_ratio": round(max_ratio, 4),
        "trend": trend,
        "trend_delta": round(delta, 4),
        "frame_count": len(results),
    })

    if best_assessment:
        yield sse({"type": "video_glmv", "assessment": best_assessment})

    summaries = [f"[{r.timestamp}s] {r.glmv.get('summary', '')}" for r in results if r.glmv.get("summary")]
    glmv_summary = " | ".join(summaries) if summaries else f"共{len(results)}帧，最大水面占比{round(max_ratio*100,1)}%"

    yield sse({"type": "thinking", "agent": "video", "content": f"🎉 视频分析完成，共{len(results)}帧，水体趋势：{trend}"})
    yield sse({
        "type": "video_analysis_done",
        "duration_s": round(duration, 1),
        "frame_count": len(results),
        "max_water_ratio": round(max_ratio, 4),
        "trend": trend,
        "trend_delta": round(delta, 4),
        "glmv_summary": glmv_summary,
        "elapsed_ms": int((time.time() - t0) * 1000),
    })
