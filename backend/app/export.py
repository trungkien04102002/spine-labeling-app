"""Build a study's export bundle (a single in-memory zip).

Contents:
  - ``original.nii.gz``  -- the viewer volume (reoriented NIfTI)
  - ``mask.nii.gz``      -- the (corrected) segmentation labelmap, if present
  - ``grades.csv``       -- one row per (level, condition) grade
  - ``grades.json``      -- the full results payload (InferResult shape)
  - ``labeled_midsag.png`` -- mid-sagittal slice with the mask blended over it

Rendered with SimpleITK/numpy only (no PIL/matplotlib dependency).
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import SimpleITK as sitk


def _label_color(label_id: int) -> tuple[int, int, int]:
    """Deterministic bright-ish RGB for a label id (0 = no color)."""
    rng = np.random.default_rng(label_id * 2654435761 % (2**32))
    return tuple(int(c) for c in rng.integers(64, 256, size=3))


def _labeled_png_bytes(display_path: str, mask_path: str | None) -> bytes | None:
    """Blend the mask over the mid-sagittal slice and return PNG bytes."""
    vol = sitk.GetArrayFromImage(sitk.ReadImage(display_path)).astype(np.float32)
    if vol.ndim != 3:
        return None
    z = vol.shape[0] // 2
    frame = vol[z]
    lo, hi = np.percentile(frame, [1, 99])
    gray = np.clip((frame - lo) / (hi - lo + 1e-8), 0, 1)
    rgb = np.stack([gray, gray, gray], axis=-1)  # (y, x, 3) in [0, 1]

    if mask_path and Path(mask_path).is_file():
        mask = sitk.GetArrayFromImage(sitk.ReadImage(mask_path))
        if mask.shape == vol.shape:
            mslice = mask[z]
            for label_id in np.unique(mslice):
                if label_id == 0:
                    continue
                color = np.array(_label_color(int(label_id))) / 255.0
                sel = mslice == label_id
                rgb[sel] = 0.5 * rgb[sel] + 0.5 * color

    rgb_u8 = (rgb * 255).astype(np.uint8)
    img = sitk.GetImageFromArray(rgb_u8, isVector=True)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
        sitk.WriteImage(img, tmp.name)
        return Path(tmp.name).read_bytes()


def _grades_csv(payload: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["level", "condition", "severity", "score", "bbox"])
    for g in payload.get("grading", []):
        writer.writerow(
            [g["level"], g["condition"], g["severity"], g["score"], g.get("bbox")]
        )
    return buf.getvalue()


def build_export_zip(
    display_path: str | None, mask_path: str | None, payload: dict
) -> bytes:
    """Assemble the export zip and return its bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("grades.csv", _grades_csv(payload))
        zf.writestr("grades.json", json.dumps(payload, indent=2))
        if display_path and Path(display_path).is_file():
            zf.writestr("original.nii.gz", Path(display_path).read_bytes())
        if mask_path and Path(mask_path).is_file():
            zf.writestr("mask.nii.gz", Path(mask_path).read_bytes())
        if display_path and Path(display_path).is_file():
            png = _labeled_png_bytes(display_path, mask_path)
            if png is not None:
                zf.writestr("labeled_midsag.png", png)
    return buf.getvalue()
