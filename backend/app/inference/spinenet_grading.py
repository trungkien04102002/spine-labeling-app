"""Upstream SpineNet grading wrapper.

Runs the vendored upstream SpineNet pipeline (``backend/spinenet/``, weights
in ``backend/spinenet/weights/`` -- gitignored, ~784MB, see CLAUDE.md) end to
end: vertebra detection -> IVD extraction -> 11-task radiological grading.
CPU-friendly (no GPU required); see ``spinenet.main.SpineNet``.

This module computes ALL 11 upstream conditions, including
``canal_stenosis`` / ``left_foraminal`` / ``right_foraminal`` -- but those
three are computed here only for completeness/testability. The app's merge
step (``app/inference/full_grading.py::merge_gradings``) unconditionally
discards them and substitutes the app's own fine-tuned CBAM model's
predictions instead (``app/inference/grading.py``). This module never renders
a "canal_stenosis"/"left_foraminal"/"right_foraminal" value that reaches the
UI without going through that swap -- see ``CBAM_OWNED_CONDITIONS``.
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
import SimpleITK as sitk
import torch
import torch.nn.functional as F

from app.inference.volume_io import _orient_slices_last, _read_image
from app.schemas import GradingItem

# backend/app/inference/spinenet_grading.py -> parents[2] == backend/
_SPINENET_PKG_PARENT = Path(__file__).resolve().parents[2]

# Conditions the app's fine-tuned CBAM model owns. SpineNet computes its own
# versions of these internally (as part of its standard 11-task head), but
# `merge_gradings` always drops them in favor of the CBAM predictions.
CBAM_OWNED_CONDITIONS = frozenset({"canal_stenosis", "left_foraminal", "right_foraminal"})

# Canonical spine order, used to normalize a detected "lower-upper" level
# (e.g. "L5-L4") into the app's "upper-lower" convention (e.g. "L4-L5") so it
# lines up with the CBAM crop levels in `app/inference/crops.py`.
_VERTEBRA_ORDER = (
    [f"T{i}" for i in range(1, 13)]
    + [f"L{i}" for i in range(1, 6)]
    + [f"S{i}" for i in range(1, 6)]
)
_VERTEBRA_RANK = {name: i for i, name in enumerate(_VERTEBRA_ORDER)}


def _normalize_level(level: str) -> str:
    """Order a "A-B" level string as "upper-lower" by canonical spine rank."""
    parts = level.split("-")
    if len(parts) != 2 or any(p not in _VERTEBRA_RANK for p in parts):
        return level
    a, b = parts
    return f"{a}-{b}" if _VERTEBRA_RANK[a] < _VERTEBRA_RANK[b] else f"{b}-{a}"


def _grade_label(value: int) -> str:
    return f"Grade {value}"


def _present_absent(value: int) -> str:
    return "Present" if value else "Absent"


def _spondylolisthesis_label(value: int) -> str:
    return {0: "None", 1: "Grade I", 2: "Grade II"}.get(value, f"Grade {value}")


# (condition_key, head_index, class_shift, label_fn). `head_index` indexes
# `GradingModel.forward()`'s 11-tuple output (pf, nar, ccs, spn, ued, led,
# umc, lmc, fsl, fsr, hrn -- see spinenet/models/grading.py). `class_shift` is
# +1 for the 3 upstream columns `format_gradings` shifts (Pfirrmann,
# Narrowing, CentralCanalStenosis); everything else is used 0-indexed.
_SPINENET_COLUMNS: list[tuple[str, int, int, Callable[[int], str]]] = [
    ("pfirrmann", 0, 1, _grade_label),
    ("disc_narrowing", 1, 1, _grade_label),
    ("canal_stenosis", 2, 1, _grade_label),  # upstream-only value; dropped at merge
    ("spondylolisthesis", 3, 0, _spondylolisthesis_label),
    ("upper_endplate_defect", 4, 0, _present_absent),
    ("lower_endplate_defect", 5, 0, _present_absent),
    ("upper_marrow", 6, 0, _present_absent),
    ("lower_marrow", 7, 0, _present_absent),
    ("left_foraminal", 8, 0, _present_absent),  # upstream-only value; dropped at merge
    ("right_foraminal", 9, 0, _present_absent),  # upstream-only value; dropped at merge
    ("disc_herniation", 10, 0, _present_absent),
]


@lru_cache(maxsize=1)
def _load_spinenet():
    """Load the upstream SpineNet pipeline once (CPU) and cache it."""
    if str(_SPINENET_PKG_PARENT) not in sys.path:
        sys.path.insert(0, str(_SPINENET_PKG_PARENT))
    from spinenet import SpineNet

    return SpineNet(device="cpu", verbose=False, scan_type="lumbar")


@dataclass
class SpineNetGradingResult:
    """Everything the full-grading endpoint needs from one SpineNet run."""

    items: list[GradingItem]
    vert_dicts: list[dict]
    volume_hws: np.ndarray  # (H, W, num_slices) -- same array detect_vb used


def _grade_ivds_with_confidence(spnt, ivd_dicts: list[dict]) -> list[GradingItem]:
    """Grade every IVD with all 11 upstream heads, keeping softmax confidence.

    Reimplements `spinenet.utils.classification.classify_ivd_v2_resnet` +
    `format_gradings`'s class-shift logic locally (rather than calling
    `SpineNet.grade_ivds`) so each head's softmax probability can be kept as
    the `GradingItem.score` -- upstream's own helper only keeps the argmax.
    Note: `classify_ivd_v2_resnet` feeds each `(9, 112, 224)` IVD volume to the
    grading model directly (batch+channel dims added); it does NOT go through
    `format_volume_for_classification_net` (that helper crops assuming an
    uncropped `(rows, cols, slices)` volume and is used by a different,
    unused-here classification path -- calling it on `get_all_ivd_vol`'s
    already-cropped `(9, 112, 224)` output produces a garbage crop).
    """
    items: list[GradingItem] = []
    for ivd in ivd_dicts:
        level = _normalize_level(ivd["level_name"])
        x = torch.from_numpy(ivd["volume"])[None, None].float().to(spnt.device)
        with torch.no_grad():
            outputs = spnt.grading_model(x)
        for condition, head_idx, shift, label_fn in _SPINENET_COLUMNS:
            probs = F.softmax(outputs[head_idx].squeeze(0), dim=0)
            cls = int(torch.argmax(probs).item())
            items.append(
                GradingItem(
                    level=level,
                    condition=condition,
                    severity=label_fn(cls + shift),
                    score=float(probs[cls].item()),
                    bbox=None,
                    heatmap_uri=None,
                )
            )
    return items


def _load_volume_for_spinenet(volume_path: str) -> tuple[np.ndarray, float]:
    """Load an app study volume into SpineNet's expected (H, W, S) + spacing.

    Best-effort general path for arbitrary uploaded volumes (DICOM/MHA/NIfTI
    read the same way the rest of the app does, via `volume_io`). The
    dedicated sample-scan validation instead uses
    `spinenet.io.load_dicoms_from_folder` directly -- the exact convention
    upstream's own `test_spinenet.py` uses -- which is what has actually been
    verified end to end (see `run_spinenet_grading_on_dicom_folder`).
    """
    image = _orient_slices_last(_read_image(volume_path))
    arr = sitk.GetArrayFromImage(image).astype(np.float32)  # (S, H, W)
    volume_hws = np.transpose(arr, (1, 2, 0))  # (H, W, S)
    sx, sy, _sz = image.GetSpacing()
    # Upstream expects a single in-plane spacing scalar (it does
    # ``patch_edge_len * 10 / pixel_spacing``); it computes the same via
    # ``np.mean(PixelSpacing)`` in ``dicom_io``. Match that: mean of the two
    # in-plane axes. Passing the (sy, sx) tuple raises TypeError deep in
    # ``split_into_patches_exhaustive``.
    pixel_spacing = float(np.mean([sy, sx]))
    return volume_hws, pixel_spacing


def run_spinenet_grading(volume_hws: np.ndarray, pixel_spacing) -> SpineNetGradingResult:
    """Run the full upstream pipeline on an already-loaded (H, W, S) volume."""
    spnt = _load_spinenet()
    vert_dicts = spnt.detect_vb(volume_hws, pixel_spacing)
    ivd_dicts = spnt.get_ivds_from_vert_dicts(vert_dicts, volume_hws)
    items = _grade_ivds_with_confidence(spnt, ivd_dicts)
    return SpineNetGradingResult(items=items, vert_dicts=vert_dicts, volume_hws=volume_hws)


def run_spinenet_grading_on_study_volume(volume_path: str) -> SpineNetGradingResult:
    """Entry point for the app: run SpineNet on a study's stored volume file."""
    volume_hws, pixel_spacing = _load_volume_for_spinenet(volume_path)
    return run_spinenet_grading(volume_hws, pixel_spacing)


def run_spinenet_grading_on_dicom_folder(folder: str) -> SpineNetGradingResult:
    """Entry point for the sample-scan validation (matches `test_spinenet.py`)."""
    if str(_SPINENET_PKG_PARENT) not in sys.path:
        sys.path.insert(0, str(_SPINENET_PKG_PARENT))
    from spinenet.io import load_dicoms_from_folder

    overwrite_dict = {
        "SliceThickness": [2],
        "ImageOrientationPatient": [0, 1, 0, 0, 0, -1],
    }
    scan = load_dicoms_from_folder(
        folder, require_extensions=False, metadata_overwrites=overwrite_dict
    )
    return run_spinenet_grading(scan.volume, scan.pixel_spacing)


def render_labelled_slice_png(result: SpineNetGradingResult) -> bytes:
    """Render the mid-sagittal slice with detected vertebra boxes + labels."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    volume = result.volume_hws
    mid = volume.shape[2] // 2
    frame = volume[:, :, mid]
    lo, hi = np.percentile(frame, [1, 99])
    gray = np.clip((frame - lo) / (hi - lo + 1e-8), 0, 1)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(gray, cmap="gray")
    ax.axis("off")
    for vert in result.vert_dicts:
        if mid not in vert.get("slice_nos", []):
            continue
        poly = np.array(vert["average_polygon"])
        x0, y0 = poly[:, 0].min(), poly[:, 1].min()
        w, h = poly[:, 0].max() - x0, poly[:, 1].max() - y0
        ax.add_patch(
            plt.Rectangle((x0, y0), w, h, fill=False, edgecolor="#00e5ff", linewidth=1.5)
        )
        ax.text(
            x0, y0 - 3, vert["predicted_label"], color="#00e5ff", fontsize=9, weight="bold"
        )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.05, dpi=150)
    plt.close(fig)
    return buf.getvalue()
