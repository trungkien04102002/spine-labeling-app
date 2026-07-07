"""Per-disc crop extraction from a segmentation mask.

The Phase-2 CBAM grading model scores one intervertebral disc at a time from a
``(9, 112, 224)`` sagittal crop centered on that disc. An uploaded volume has no
pre-made crops, so we localize each lumbar disc using TotalSpineSeg's disc
labels and cut a crop the same way the RSNA preprocessing did (9 slices around
the disc's sagittal slice; a 240x120 in-plane window around its centroid,
resized to 224x112; percentile-normalized to [0, 1]).

This deliberately consumes the segmentation output to drive grading -- a
seg->grading chain the project owner approved (see the LVTN software chapter).
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F

# TotalSpineSeg disc label id -> grading level string. Only the five lumbar
# levels the Phase-2 model was trained on.
DISC_LABEL_TO_LEVEL: dict[int, str] = {
    92: "L1-L2",
    93: "L2-L3",
    94: "L3-L4",
    95: "L4-L5",
    100: "L5-S1",
}

# In-plane crop box (RSNA convention): 240 wide x 120 high, then resize to
# 224 x 112 (width x height). 9 slices centered on the disc's sagittal slice.
_CROP_W = 240
_CROP_H = 120
_OUT_W = 224
_OUT_H = 112
_N_SLICES = 9


def _normalize(volume: np.ndarray) -> np.ndarray:
    """Percentile-clip to [1, 99] and rescale to [0, 1] (RSNA preprocessing)."""
    p1, p99 = np.percentile(volume, [1, 99])
    volume = np.clip(volume, p1, p99)
    return ((volume - p1) / (p99 - p1 + 1e-8)).astype(np.float32)


def _crop_one(
    vol_arr: np.ndarray, slice_c: int, y_c: int, x_c: int
) -> np.ndarray:
    """Build one ``(9, 112, 224)`` crop centered at (slice_c, y_c, x_c).

    ``vol_arr`` is the volume as ``(num_slices, H, W)`` (SimpleITK z, y, x).
    """
    num_slices, height, width = vol_arr.shape
    x1 = max(0, x_c - _CROP_W // 2)
    y1 = max(0, y_c - _CROP_H // 2)
    x2 = min(width, x1 + _CROP_W)
    y2 = min(height, y1 + _CROP_H)

    slices: list[np.ndarray] = []
    for offset in range(-(_N_SLICES // 2), _N_SLICES // 2 + 1):  # -4..+4
        idx = min(max(slice_c + offset, 0), num_slices - 1)
        cropped = vol_arr[idx, y1:y2, x1:x2].astype(np.float32)
        # Bilinear resize to (H=112, W=224) via torch (avoids an opencv dep).
        tensor = torch.from_numpy(cropped)[None, None]  # (1, 1, H, W)
        resized = F.interpolate(
            tensor, size=(_OUT_H, _OUT_W), mode="bilinear", align_corners=False
        )[0, 0].numpy()
        slices.append(resized)

    return _normalize(np.stack(slices, axis=0))


def extract_disc_crops(
    vol_arr: np.ndarray, mask_arr: np.ndarray
) -> dict[str, dict[str, object]]:
    """Extract a grading crop per lumbar disc present in ``mask_arr``.

    Both arrays must share the same ``(num_slices, H, W)`` shape and orientation
    (i.e. the reoriented display volume + its aligned labelmap).

    Returns:
        ``{level: {"crop": np.ndarray(9,112,224), "bbox": [slice, x1, y1, x2, y2]}}``
        keyed by level string (e.g. "L4-L5"); ``bbox`` is the disc's center
        sagittal slice + its in-plane extent, in display-volume voxels, for the
        viewer to draw a box / jump to the disc.
    """
    out: dict[str, dict[str, object]] = {}
    for label_id, level in DISC_LABEL_TO_LEVEL.items():
        coords = np.argwhere(mask_arr == label_id)
        if coords.size == 0:
            continue
        # coords columns are (slice, y, x).
        slice_c = int(round(coords[:, 0].mean()))
        y_c = int(round(coords[:, 1].mean()))
        x_c = int(round(coords[:, 2].mean()))
        y_min, x_min = coords[:, 1].min(), coords[:, 2].min()
        y_max, x_max = coords[:, 1].max(), coords[:, 2].max()

        out[level] = {
            "crop": _crop_one(vol_arr, slice_c, y_c, x_c),
            "bbox": [
                float(slice_c),
                float(x_min),
                float(y_min),
                float(x_max),
                float(y_max),
            ],
        }
    return out
