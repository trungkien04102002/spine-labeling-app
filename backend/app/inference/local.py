"""In-process inference backend.

Runs TotalSpineSeg for anatomy masks, then grades each lumbar disc using crops
that the segmentation localizes (seg->grading chain, approved by the project
owner: an uploaded volume ships no per-disc crops, so the mask is what tells us
where each disc is).
"""

from __future__ import annotations

import SimpleITK as sitk

from app.inference.base import InferenceBackend
from app.inference.crops import extract_disc_crops
from app.inference.grading import grade_crops
from app.inference.segmentation import run_segmentation
from app.inference.volume_io import _orient_slices_last, _read_image
from app.schemas import InferResult, SegmentationResult

MODEL_VERSION = "phase2-cbam + totalspineseg-r20241115"


def _crops_from_mask(volume_path: str, mask_path: str) -> dict:
    """Reorient volume + mask identically (so voxels align) and cut disc crops."""
    vol_arr = sitk.GetArrayFromImage(_orient_slices_last(_read_image(volume_path)))
    mask_arr = sitk.GetArrayFromImage(_orient_slices_last(_read_image(mask_path)))
    return extract_disc_crops(vol_arr, mask_arr)


class LocalBackend(InferenceBackend):
    def infer(
        self,
        study_id: str,
        volume_path: str,
        grading_dir: str | None = None,  # unused; kept for interface parity
    ) -> InferResult:
        mask_path, labels = run_segmentation(volume_path)
        crops = _crops_from_mask(volume_path, mask_path)
        grading = grade_crops(crops)

        return InferResult(
            study_id=study_id,
            segmentation=SegmentationResult(mask_uri=mask_path, labels=labels),
            grading=grading,
            model_version=MODEL_VERSION,
        )
