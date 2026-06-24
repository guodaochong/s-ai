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


@dataclass
class FrameResult:
    timestamp: float
    frame_idx: int
    water_ratio: float
    water_changed: float
    annotated_b64: str
    contours_count: int
    dominant_hue: float


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
    mask = cv2.inRange(hsv, _HSV_LOWER, _HSV_UPPER)
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


def analyze_frames(frames: list[tuple[int, float, np.ndarray]]) -> list[FrameResult]:
    results: list[FrameResult] = []
    prev_ratio = 0.0

    for fidx, ts, frame in frames:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask, ratio = _detect_water(hsv)
        changed = ratio - prev_ratio

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        significant = [c for c in contours if cv2.contourArea(c) > mask.size * _MIN_AREA_RATIO]

        annotated = _annotate_frame(frame, mask)
        for c in significant:
            x, y, w, h = cv2.boundingRect(c)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 100), 2)

        hue_vals = hsv[mask > 0, 0]
        dom_hue = float(np.mean(hue_vals)) if len(hue_vals) > 0 else 0.0

        results.append(FrameResult(
            timestamp=round(ts, 1),
            frame_idx=fidx,
            water_ratio=round(ratio, 4),
            water_changed=round(changed, 4),
            annotated_b64=_frame_to_b64(annotated),
            contours_count=len(significant),
            dominant_hue=round(dom_hue, 1),
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

    yield sse({"type": "thinking", "agent": "video", "content": "🌊 正在进行水体检测..."})
    results = analyze_frames(frames)

    for i, r in enumerate(results):
        yield sse({
            "type": "video_frame_result",
            "frame_idx": i,
            "total": len(results),
            "timestamp": r.timestamp,
            "water_ratio": r.water_ratio,
            "water_changed": r.water_changed,
            "contours_count": r.contours_count,
            "frame_b64": r.annotated_b64,
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

    glmv_data: dict[str, Any] = {}
    if use_glmv:
        yield sse({"type": "thinking", "agent": "video", "content": "🧠 GLM-4V 正在分析关键帧..."})
        glmv_data = await glmv_video_assess(frames, user_context)
        if glmv_data.get("assessment"):
            yield sse({"type": "video_glmv", "assessment": glmv_data["assessment"]})
        yield sse({"type": "thinking", "agent": "video", "content": f"✅ GLM-4V分析完成: {glmv_data.get('summary', '')[:100]}"})

    yield sse({"type": "thinking", "agent": "video", "content": f"🎉 视频分析完成，共{len(results)}帧，水体趋势：{trend}"})
    yield sse({
        "type": "video_analysis_done",
        "duration_s": round(duration, 1),
        "frame_count": len(results),
        "max_water_ratio": round(max_ratio, 4),
        "trend": trend,
        "trend_delta": round(delta, 4),
        "glmv_summary": glmv_data.get("summary", ""),
        "elapsed_ms": int((time.time() - t0) * 1000),
    })
