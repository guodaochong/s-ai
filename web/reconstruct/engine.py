import os
import sys
import time
import uuid
import json
import asyncio
import traceback
from pathlib import Path
from typing import Optional

RECON_DIR = Path(__file__).resolve().parent
TRIPOSR_DIR = RECON_DIR / "TripoSR"
sys.path.insert(0, str(TRIPOSR_DIR))

import torch
import numpy as np
from PIL import Image

_tasks: dict = {}


def _progress_cb(task_id: str, stage: str, pct: float, detail: str = ""):
    if task_id in _tasks:
        _tasks[task_id]["stage"] = stage
        _tasks[task_id]["progress"] = pct
        _tasks[task_id]["detail"] = detail


class ReconstructionEngine:
    _instance: Optional["ReconstructionEngine"] = None
    _model = None
    _rembg_session = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_model(self):
        if self._model is not None:
            return
        from tsr.system import TSR
        ckpt = str(TRIPOSR_DIR / "checkpoints" / "model.ckpt")
        cfg = str(TRIPOSR_DIR / "config.yaml")
        self._model = TSR.from_pretrained(
            TRIPOSR_DIR,
            config_name="config.yaml",
            weight_name="checkpoints/model.ckpt",
        )
        self._model.renderer.set_chunk_size(4096)
        self._model.to("cuda:0")

    def _ensure_rembg(self):
        if self._rembg_session is not None:
            return
        import rembg
        self._rembg_session = rembg.new_session()

    def reconstruct_single(
        self,
        image_path: str,
        task_id: str,
        mc_resolution: int = 256,
        remove_bg: bool = True,
        foreground_ratio: float = 0.85,
    ) -> str:
        from tsr.utils import remove_background, resize_foreground

        task_dir = RECON_DIR / "outputs" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        _tasks[task_id] = {
            "stage": "loading_model",
            "progress": 0,
            "detail": "Loading TripoSR model...",
            "output": None,
            "error": None,
        }

        try:
            _progress_cb(task_id, "loading_model", 5, "Loading TripoSR model...")
            self._ensure_model()
            self._ensure_rembg()

            _progress_cb(task_id, "preprocessing", 15, "Preprocessing image...")
            raw = Image.open(image_path).convert("RGB")
            raw.save(str(task_dir / "input_original.png"))

            if remove_bg:
                img = remove_background(raw, self._rembg_session)
                img = resize_foreground(img, foreground_ratio)
                arr = np.array(img).astype(np.float32) / 255.0
                arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5
                img = Image.fromarray((arr * 255.0).astype(np.uint8))
            else:
                img = raw

            img.save(str(task_dir / "input.png"))

            _progress_cb(task_id, "inference", 30, "Running TripoSR inference...")
            t0 = time.time()
            with torch.no_grad():
                scene_codes = self._model([img], device="cuda:0")
            inf_time = time.time() - t0

            _progress_cb(task_id, "extracting_mesh", 60, f"Extracting mesh (resolution={mc_resolution})...")
            t1 = time.time()
            meshes = self._model.extract_mesh(scene_codes, True, resolution=mc_resolution)
            mesh_time = time.time() - t1
            mesh = meshes[0]

            _progress_cb(task_id, "exporting", 85, "Exporting GLB...")
            glb_path = task_dir / "output.glb"
            mesh.export(str(glb_path))

            meta = {
                "vertices": int(len(mesh.vertices)),
                "faces": int(len(mesh.faces)),
                "inference_time": round(inf_time, 2),
                "mesh_time": round(mesh_time, 2),
                "total_time": round(inf_time + mesh_time, 2),
                "vram_peak_gb": round(
                    torch.cuda.max_memory_allocated() / 1024**3, 2
                ),
                "has_color": mesh.visual is not None,
            }
            (task_dir / "meta.json").write_text(json.dumps(meta, indent=2))

            _tasks[task_id]["output"] = str(glb_path)
            _tasks[task_id]["meta"] = meta
            _progress_cb(task_id, "done", 100, "Done!")

            torch.cuda.empty_cache()
            return str(glb_path)

        except Exception as e:
            tb = traceback.format_exc()
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["traceback"] = tb
            _progress_cb(task_id, "error", 100, str(e))
            raise


def create_task() -> str:
    tid = uuid.uuid4().hex[:12]
    _tasks[tid] = {
        "stage": "queued",
        "progress": 0,
        "detail": "",
        "output": None,
        "error": None,
    }
    return tid


def get_task_status(task_id: str) -> dict:
    return _tasks.get(task_id, {"error": "Task not found"})


engine = ReconstructionEngine.get_instance()
