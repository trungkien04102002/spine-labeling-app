"""TotalSpineSeg segmentation wrapper.

TotalSpineSeg (nnU-Net based) segments and labels vertebrae, intervertebral
discs, spinal cord and spinal canal from a spine MRI. It pins ``numpy<2`` and
pulls in nnU-Net/torchio, which conflict with this backend's torch/numpy, so it
is NOT imported in-process. Instead we shell out to its CLI (``totalspineseg``),
which is expected to live in its own environment; the path is configurable via
``Settings.totalspineseg_bin``.

``run_segmentation(volume_path)`` runs the CLI on a single NIfTI volume, locates
the final labelmap in the tool's ``step2_output/`` folder, and returns
``(mask_path, labels)`` where ``labels`` maps each present label id to its
anatomical name.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import nibabel as nib
import numpy as np

from app.config import Settings

# Final ``step2_output`` labelmap of TotalSpineSeg (release r20241115). Source:
# the label table in the TotalSpineSeg README. Only lumbar-relevant + spinal
# structures matter for this app, but the full spine map is kept for fidelity.
TOTALSPINESEG_LABELS: dict[int, str] = {
    1: "spinal_cord",
    2: "spinal_canal",
    11: "vertebrae_C1",
    12: "vertebrae_C2",
    13: "vertebrae_C3",
    14: "vertebrae_C4",
    15: "vertebrae_C5",
    16: "vertebrae_C6",
    17: "vertebrae_C7",
    21: "vertebrae_T1",
    22: "vertebrae_T2",
    23: "vertebrae_T3",
    24: "vertebrae_T4",
    25: "vertebrae_T5",
    26: "vertebrae_T6",
    27: "vertebrae_T7",
    28: "vertebrae_T8",
    29: "vertebrae_T9",
    30: "vertebrae_T10",
    31: "vertebrae_T11",
    32: "vertebrae_T12",
    41: "vertebrae_L1",
    42: "vertebrae_L2",
    43: "vertebrae_L3",
    44: "vertebrae_L4",
    45: "vertebrae_L5",
    50: "sacrum",
    63: "disc_C2_C3",
    64: "disc_C3_C4",
    65: "disc_C4_C5",
    66: "disc_C5_C6",
    67: "disc_C6_C7",
    71: "disc_C7_T1",
    72: "disc_T1_T2",
    73: "disc_T2_T3",
    74: "disc_T3_T4",
    75: "disc_T4_T5",
    76: "disc_T5_T6",
    77: "disc_T6_T7",
    78: "disc_T7_T8",
    79: "disc_T8_T9",
    80: "disc_T9_T10",
    81: "disc_T10_T11",
    82: "disc_T11_T12",
    91: "disc_T12_L1",
    92: "disc_L1_L2",
    93: "disc_L2_L3",
    94: "disc_L3_L4",
    95: "disc_L4_L5",
    100: "disc_L5_S",
}

# Folder inside the TotalSpineSeg output that holds the final labelmap.
_FINAL_OUTPUT_DIR = "step2_output"


def _labels_present(mask_path: str) -> dict[int, str]:
    """Return the subset of ``TOTALSPINESEG_LABELS`` present in ``mask_path``.

    Background (0) and any id not in the known map are excluded.
    """
    mask = nib.load(mask_path)
    values = np.unique(np.asarray(mask.dataobj))
    present: dict[int, str] = {}
    for value in values:
        label_id = int(value)
        if label_id in TOTALSPINESEG_LABELS:
            present[label_id] = TOTALSPINESEG_LABELS[label_id]
    return present


def _find_labelmap(output_path: Path) -> Path:
    """Locate the single final labelmap NIfTI under ``step2_output/``."""
    step2_dir = output_path / _FINAL_OUTPUT_DIR
    if not step2_dir.is_dir():
        raise FileNotFoundError(
            f"TotalSpineSeg produced no {_FINAL_OUTPUT_DIR}/ in {output_path}"
        )
    masks = sorted(step2_dir.glob("*.nii.gz")) + sorted(step2_dir.glob("*.nii"))
    if not masks:
        raise FileNotFoundError(f"No labelmap NIfTI found in {step2_dir}")
    return masks[0]


def _ensure_nifti(volume_path: str, work_dir: Path) -> Path:
    """Return a NIfTI path for ``volume_path``, converting if needed."""
    src = Path(volume_path)
    if src.is_file() and (
        src.name.endswith(".nii") or src.name.endswith(".nii.gz")
    ):
        return src
    import SimpleITK as sitk

    from app.inference.volume_io import _read_image

    converted = work_dir / "seg_input.nii.gz"
    sitk.WriteImage(_read_image(volume_path), str(converted))
    return converted


def run_segmentation(
    volume_path: str,
    output_dir: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, dict[int, str]]:
    """Run TotalSpineSeg on one NIfTI volume.

    Args:
        volume_path: path to a ``.nii`` / ``.nii.gz`` spine MRI volume.
        output_dir: where the tool writes its output tree; a temp dir is used
            if omitted (the returned mask still lives under it, so callers that
            omit this should copy the mask out before it is cleaned up).
        settings: override settings (mainly for tests); defaults to ``Settings()``.

    Returns:
        ``(mask_path, labels)`` -- absolute path to the final labelmap NIfTI and
        a mapping of present label id -> anatomical name.
    """
    settings = settings or Settings()

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="totalspineseg_")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # The TotalSpineSeg CLI only accepts NIfTI. Convert other inputs (e.g. the
    # SPIDER .mha, a DICOM series dir) to a temp .nii.gz first.
    nifti_input = _ensure_nifti(volume_path, output_path)

    cmd = [
        settings.totalspineseg_bin,
        str(nifti_input),
        str(output_path),
        "--device",
        settings.seg_device,
        "--quiet",
    ]
    if settings.totalspineseg_data:
        cmd += ["--data-dir", settings.totalspineseg_data]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "TotalSpineSeg failed "
            f"(exit {result.returncode}).\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    mask_path = _find_labelmap(output_path)
    labels = _labels_present(str(mask_path))
    return str(mask_path.resolve()), labels
