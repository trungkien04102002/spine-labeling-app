"""Remote inference backend.

Posts the study volume to a standalone model server running on a Vast.ai box
(see the repo-root `serve_models.py`), which exposes `/seg` and `/grade`. The
segmentation mask stays on the remote and is referenced by URL in `mask_uri`.
"""

from __future__ import annotations

import httpx

from app.inference.base import InferenceBackend
from app.schemas import GradingItem, InferResult, SegmentationResult

_DEFAULT_TIMEOUT = 900.0  # seg on CPU can take minutes


class RemoteVastBackend(InferenceBackend):
    def __init__(
        self,
        vast_url: str,
        client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.vast_url = vast_url.rstrip("/")
        self._client = client or httpx.Client(
            base_url=self.vast_url, timeout=timeout
        )

    def infer(
        self,
        study_id: str,
        volume_path: str,
        grading_dir: str | None = None,
    ) -> InferResult:
        with open(volume_path, "rb") as fh:
            seg_resp = self._client.post("/seg", files={"file": fh})
        seg_resp.raise_for_status()
        seg = seg_resp.json()

        with open(volume_path, "rb") as fh:
            grade_resp = self._client.post("/grade", files={"file": fh})
        grade_resp.raise_for_status()
        grades = grade_resp.json()["grading"]

        return InferResult(
            study_id=study_id,
            segmentation=SegmentationResult(
                mask_uri=seg["mask_uri"], labels=seg["labels"]
            ),
            grading=[GradingItem(**item) for item in grades],
            model_version=seg.get("model_version", "remote"),
        )
