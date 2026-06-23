"""3D reconstruction routes — TripoSR image-to-mesh pipeline (async background tasks).

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, File as FastAPIFile, UploadFile
from starlette.responses import FileResponse

from app.config import RECON_OUTPUTS
from app.services import get_recon_engine

router = APIRouter()

RECON_OUTPUTS.mkdir(parents=True, exist_ok=True)


@router.post("/api/reconstruct/upload")
async def reconstruct_upload(file: UploadFile = FastAPIFile(...)):
    from reconstruct.engine import create_task, get_task_status, _tasks

    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"):
        return {"error": f"Unsupported format: {ext}"}

    task_id = create_task()
    task_dir = RECON_OUTPUTS / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    img_path = task_dir / f"input{ext}"
    content = await file.read()
    img_path.write_bytes(content)

    def _run():
        try:
            eng = get_recon_engine()
            eng.reconstruct_single(str(img_path), task_id)
        except Exception as e:
            if task_id in _tasks:
                _tasks[task_id]["error"] = str(e)
                _tasks[task_id]["stage"] = "error"

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {"task_id": task_id}


@router.get("/api/reconstruct/status/{task_id}")
async def reconstruct_status(task_id: str):
    from reconstruct.engine import get_task_status
    return get_task_status(task_id)


@router.get("/api/reconstruct/result/{task_id}")
async def reconstruct_result(task_id: str):
    from reconstruct.engine import get_task_status
    status = get_task_status(task_id)
    glb = status.get("output")
    if glb and Path(glb).exists():
        return FileResponse(glb, media_type="model/gltf-binary", filename=f"reconstruction_{task_id}.glb")
    return {"error": "Result not ready"}


@router.get("/api/reconstruct/preview/{task_id}")
async def reconstruct_preview(task_id: str):
    from reconstruct.engine import get_task_status
    status = get_task_status(task_id)
    meta = status.get("meta", {})
    return {
        "task_id": task_id,
        "stage": status.get("stage"),
        "progress": status.get("progress", 0),
        "meta": meta,
        "error": status.get("error"),
    }
