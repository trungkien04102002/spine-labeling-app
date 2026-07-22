"""Full 11-label grading: upstream SpineNet (8 labels) + fine-tuned CBAM (3).

HONESTY CONTRACT (see CLAUDE.md / thesis software chapter): ``canal_stenosis``,
``left_foraminal``, and ``right_foraminal`` in the merged table always come
from the app's own fine-tuned CBAM model (``app/inference/grading.py``),
never from upstream SpineNet -- even though SpineNet computes its own
versions of these three internally as part of its standard 11-task head (see
``spinenet_grading.CBAM_OWNED_CONDITIONS``), ``merge_gradings`` unconditionally
discards them in favor of the CBAM predictions. This is the app's one
authoritative place enforcing which model sources which column.
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
from app.inference.volume_io import _orient_slices_last, _read_image
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


def run_cbam_grading(volume_path: str) -> list[GradingItem]:
    """Run the existing seg -> crop -> CBAM grading path (unchanged; see
    `app/inference/local.py::LocalBackend`) to get canal/foraminal items."""
    mask_path, _labels = run_segmentation(volume_path)
    vol_arr = sitk.GetArrayFromImage(_orient_slices_last(_read_image(volume_path)))
    mask_arr = sitk.GetArrayFromImage(_orient_slices_last(_read_image(mask_path)))
    crops = extract_disc_crops(vol_arr, mask_arr)
    return grade_crops(crops)


def build_full_grading(
    study_id: str, volume_path: str
) -> tuple[FullGradingResult, bytes]:
    """Run SpineNet + the CBAM path, merge them, and render the labelled slice.

    Returns:
        ``(result, slice_png_bytes)`` -- the caller persists both to disk.
    """
    cbam_items = run_cbam_grading(volume_path)
    spinenet_result = run_spinenet_grading_on_study_volume(volume_path)
    merged = merge_gradings(spinenet_result.items, cbam_items)
    png = render_labelled_slice_png(spinenet_result)
    result = FullGradingResult(
        study_id=study_id,
        grading=merged,
        slice_image_uri=f"/studies/{study_id}/grade_full/slice.png",
        model_version="spinenet-upstream + phase2-cbam",
    )
    return result, png


def grading_to_csv(grading: list[GradingItem]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["level", "condition", "severity", "score"])
    for g in grading:
        writer.writerow([g.level, g.condition, g.severity, g.score])
    return buf.getvalue()


def grading_to_json(result: FullGradingResult) -> str:
    return json.dumps(result.model_dump(), indent=2)
