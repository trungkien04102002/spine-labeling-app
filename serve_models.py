"""Standalone model server for remote (Vast.ai) inference.

Runs on the GPU box next to the model weights and exposes two endpoints that
`backend/app/inference/remote.py:RemoteVastBackend` calls:

  POST /seg    (multipart volume) -> {mask_uri, labels, model_version}
  POST /grade  (multipart volume) -> {grading: [GradingItem, ...]}

Segmentation masks are written under ./served_masks and served back via the
`/masks/<name>` static mount, so `mask_uri` is a URL the app/frontend can fetch.

Run:  uvicorn serve_models:app --host 0.0.0.0 --port 9000
(requires the backend package importable + the TotalSpineSeg CLI installed)
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile
from fastapi.staticfiles import StaticFiles

# Make the backend package importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.inference.grading import run_grading  # noqa: E402
from app.inference.local import MODEL_VERSION  # noqa: E402
from app.inference.segmentation import run_segmentation  # noqa: E402

_MASKS_DIR = Path("./served_masks").resolve()
_MASKS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="spine-labeling model server")
app.mount("/masks", StaticFiles(directory=str(_MASKS_DIR)), name="masks")


def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "volume").suffix or ".mha"
    tmp = Path(tempfile.mkdtemp()) / f"upload{suffix}"
    with tmp.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return tmp


@app.post("/seg")
def seg(file: UploadFile, request: Request) -> dict:
    volume = _save_upload(file)
    mask_path, labels = run_segmentation(str(volume))

    # Publish the mask under the static mount so the client can fetch it.
    served_name = f"{uuid.uuid4().hex}.nii.gz"
    shutil.copy(mask_path, _MASKS_DIR / served_name)
    mask_uri = str(request.base_url).rstrip("/") + f"/masks/{served_name}"

    return {"mask_uri": mask_uri, "labels": labels, "model_version": MODEL_VERSION}


@app.post("/grade")
def grade(file: UploadFile) -> dict:
    volume = _save_upload(file)
    grading = run_grading(str(volume.parent))
    return {"grading": [item.model_dump() for item in grading]}
