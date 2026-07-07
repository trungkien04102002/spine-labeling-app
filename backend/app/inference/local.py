"""In-process inference backend.

Runs the two independent models in parallel (they never chain): TotalSpineSeg
for anatomy masks and the Phase-2 CBAM grading model for per-disc grades.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.inference.base import InferenceBackend
from app.inference.grading import run_grading
from app.inference.segmentation import run_segmentation
from app.schemas import InferResult, SegmentationResult

MODEL_VERSION = "phase2-cbam + totalspineseg-r20241115"


class LocalBackend(InferenceBackend):
    def infer(
        self,
        study_id: str,
        volume_path: str,
        grading_dir: str | None = None,
    ) -> InferResult:
        # Grading consumes per-IVD .npy crops; default to the volume's folder.
        grading_dir = grading_dir or str(Path(volume_path).parent)

        with ThreadPoolExecutor(max_workers=2) as pool:
            seg_future = pool.submit(run_segmentation, volume_path)
            grade_future = pool.submit(run_grading, grading_dir)
            mask_path, labels = seg_future.result()
            grading = grade_future.result()

        return InferResult(
            study_id=study_id,
            segmentation=SegmentationResult(mask_uri=mask_path, labels=labels),
            grading=grading,
            model_version=MODEL_VERSION,
        )
