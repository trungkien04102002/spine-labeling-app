"""Tests for seg-driven per-disc crop extraction."""

import numpy as np

from app.inference.crops import DISC_LABEL_TO_LEVEL, extract_disc_crops


def _synthetic(num_slices=12, h=300, w=200):
    """A volume + mask with two lumbar disc blobs at known locations."""
    vol = np.random.default_rng(0).random((num_slices, h, w)).astype(np.float32)
    mask = np.zeros((num_slices, h, w), dtype=np.uint16)
    # disc_L4_L5 (95) blob and disc_L5_S (100) blob.
    mask[5:8, 100:120, 80:100] = 95
    mask[6:9, 150:170, 90:110] = 100
    return vol, mask


def test_extract_returns_crop_and_bbox_per_present_disc():
    vol, mask = _synthetic()
    crops = extract_disc_crops(vol, mask)

    assert set(crops) == {"L4-L5", "L5-S1"}
    for data in crops.values():
        assert data["crop"].shape == (9, 112, 224)
        # Normalized to [0, 1].
        assert data["crop"].min() >= 0.0 and data["crop"].max() <= 1.0
        # bbox = [center_slice, x1, y1, x2, y2].
        assert len(data["bbox"]) == 5


def test_absent_discs_are_skipped():
    vol = np.zeros((10, 200, 200), dtype=np.float32)
    mask = np.zeros((10, 200, 200), dtype=np.uint16)  # no disc labels
    assert extract_disc_crops(vol, mask) == {}


def test_only_lumbar_disc_labels_are_used():
    vol = np.zeros((10, 200, 200), dtype=np.float32)
    mask = np.zeros((10, 200, 200), dtype=np.uint16)
    mask[2:4, 20:40, 20:40] = 2  # spinal_canal — not a disc
    mask[2:4, 60:80, 60:80] = 95  # disc_L4_L5
    crops = extract_disc_crops(vol, mask)
    assert set(crops) == {"L4-L5"}
    assert 95 in DISC_LABEL_TO_LEVEL
