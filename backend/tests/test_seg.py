"""Tests for the TotalSpineSeg segmentation wrapper.

The label-mapping logic is tested with a tiny synthetic labelmap (fast). The
real end-to-end nnU-Net run is heavy (two models, minutes on CPU) and depends
on the external `totalspineseg` CLI + weights, so it is gated behind the
`RUN_SEG_TEST=1` env var and skipped otherwise.
"""

import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from app.config import Settings
from app.inference.segmentation import (
    TOTALSPINESEG_LABELS,
    _labels_present,
    run_segmentation,
)

nib = pytest.importorskip("nibabel")

# A lumbar sagittal MRI must at least be able to surface these structures.
_LUMBAR_NAMES = {
    "spinal_canal",
    "vertebrae_L1",
    "vertebrae_L5",
    "disc_L1_L2",
    "disc_L4_L5",
    "disc_L5_S",
}


def test_label_map_covers_lumbar_structures():
    names = set(TOTALSPINESEG_LABELS.values())
    assert _LUMBAR_NAMES <= names


def test_labels_present_from_synthetic_mask(tmp_path):
    # Build a 4x4x4 labelmap containing background + three known labels.
    arr = np.zeros((4, 4, 4), dtype=np.uint8)
    arr[0, 0, 0] = 2  # spinal_canal
    arr[1, 1, 1] = 41  # vertebrae_L1
    arr[2, 2, 2] = 92  # disc_L1_L2
    mask_path = tmp_path / "mask.nii.gz"
    nib.save(nib.Nifti1Image(arr, np.eye(4)), str(mask_path))

    labels = _labels_present(str(mask_path))

    assert labels == {
        2: "spinal_canal",
        41: "vertebrae_L1",
        92: "disc_L1_L2",
    }
    # Background (0) is excluded.
    assert 0 not in labels


def test_labels_present_ignores_unknown_ids(tmp_path):
    arr = np.zeros((3, 3, 3), dtype=np.uint8)
    arr[0, 0, 0] = 2  # known
    arr[1, 1, 1] = 250  # not in the TotalSpineSeg map
    mask_path = tmp_path / "mask.nii.gz"
    nib.save(nib.Nifti1Image(arr, np.eye(4)), str(mask_path))

    labels = _labels_present(str(mask_path))
    assert labels == {2: "spinal_canal"}


_SAMPLE_VOLUME = Path("/Users/kienha/totalspineseg/sample/Img_01.nii")


@pytest.mark.skipif(
    os.environ.get("RUN_SEG_TEST") != "1",
    reason="heavy nnU-Net run; set RUN_SEG_TEST=1 to enable",
)
@pytest.mark.skipif(
    shutil.which(Settings().totalspineseg_bin) is None
    and not Path(Settings().totalspineseg_bin).exists(),
    reason="totalspineseg CLI not available",
)
@pytest.mark.skipif(
    not _SAMPLE_VOLUME.exists(), reason="sample volume not present"
)
def test_run_segmentation_end_to_end(tmp_path):
    mask_path, labels = run_segmentation(
        str(_SAMPLE_VOLUME), output_dir=str(tmp_path / "seg_out")
    )

    assert Path(mask_path).exists()
    assert len(labels) > 1
    for label_id, name in labels.items():
        assert TOTALSPINESEG_LABELS[label_id] == name
