"""Full 11-label grading: upstream SpineNet (8 labels) + fine-tuned CBAM (3).

``canal_stenosis``, ``left_foraminal`` and ``right_foraminal`` in the merged
table always come from the fine-tuned CBAM model (``app/inference/grading.py``),
never from SpineNet. SpineNet also predicts these three internally (see
``spinenet_grading.CBAM_OWNED_CONDITIONS``), but ``merge_gradings`` always
discards them. This is the single place that decides which model sources
which column.
"""

from __future__ import annotations

import csv
import io
import json

import SimpleITK as sitk

from app.inference.crops import extract_disc_crops
from app.inference.grading import grade_crops
from app.inference.segmentation import run_segmentation
from app.inference.spinenet_grading import (
    CBAM_OWNED_CONDITIONS,
    render_labelled_slice_png,
    run_spinenet_grading_on_study_volume,
)
from app.inference.volume_io import _read_image, to_model_orientation
from app.schemas import FullGradingResult, GradingItem


def merge_gradings(
    spinenet_items: list[GradingItem], cbam_items: list[GradingItem]
) -> list[GradingItem]:
    """Combine SpineNet's 8 labels with the CBAM model's 3, by (level, condition).

    Any SpineNet item whose condition is CBAM-owned (canal/foraminal) is
    dropped unconditionally, regardless of whether ``cbam_items`` actually has
    a replacement for every level; the CBAM items are what's used for those
    conditions. CBAM items for conditions SpineNet doesn't cover pass through
    unchanged.
    """
    kept_spinenet = [i for i in spinenet_items if i.condition not in CBAM_OWNED_CONDITIONS]
    return kept_spinenet + list(cbam_items)


def grade_with_cbam(volume_path: str, mask_path: str) -> list[GradingItem]:
    """Grade canal/foraminal items with CBAM from an existing segmentation."""
    # Image and labelmap go through the same reorientation so they stay
    # aligned voxel for voxel (the labelmap shares the input's geometry).
    vol_arr = sitk.GetArrayFromImage(to_model_orientation(_read_image(volume_path)))
    mask_arr = sitk.GetArrayFromImage(to_model_orientation(_read_image(mask_path)))
    crops = extract_disc_crops(vol_arr, mask_arr)
    return grade_crops(crops)


def build_full_grading(
    study_id: str, volume_path: str, progress=None
) -> tuple[FullGradingResult, bytes, str, dict[int, str]]:
    """Run SpineNet + the CBAM path, merge them, and render the labelled slice.

    Args:
        progress: optional ``(stage, percent, **partial) -> None`` callback,
            called at stage boundaries only. Segmentation reports no progress
            of its own, so the percentage is not interpolated (a fake smooth
            bar would hide a stall). Once the segmentation exists it is passed
            as ``mask_path=`` / ``labels=`` so the caller can show it early.

    Returns:
        ``(result, slice_png_bytes, mask_path, labels)`` -- the caller persists
        the JSON, the PNG, and the segmentation mask (``mask_path`` is the raw
        labelmap the CBAM path already produced; the caller reorients it into the
        study dir and fills ``result.segmentation``).
    """
    def report(stage: str, percent: int, **partial) -> None:
        if progress is not None:
            progress(stage, percent, **partial)

    # The longest step.
    report("Segmenting vertebrae", 10)
    mask_path, labels = run_segmentation(volume_path)
    # The segmentation is reported before grading so the viewer can show it
    # first, rather than everything arriving at once at the end.
    report("Segmentation ready. Grading each disc", 50, mask_path=mask_path, labels=labels)
    cbam_items = grade_with_cbam(volume_path, mask_path)

    report("Detecting and grading discs", 70)
    spinenet_result = run_spinenet_grading_on_study_volume(volume_path)

    report("Merging results", 90)
    merged = merge_gradings(spinenet_result.items, cbam_items)
    png = render_labelled_slice_png(spinenet_result)
    result = FullGradingResult(
        study_id=study_id,
        grading=merged,
        slice_image_uri=f"/studies/{study_id}/grade_full/slice.png",
        model_version="spinenet-upstream + phase2-cbam",
    )
    return result, png, mask_path, labels


def grading_to_csv(grading: list[GradingItem]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["level", "condition", "severity", "score"])
    for g in grading:
        writer.writerow([g.level, g.condition, g.severity, g.score])
    return buf.getvalue()


def grading_to_json(result: FullGradingResult) -> str:
    return json.dumps(result.model_dump(), indent=2)
