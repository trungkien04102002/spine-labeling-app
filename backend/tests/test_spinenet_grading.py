"""Real end-to-end validation of the vendored upstream SpineNet pipeline.

Runs on the sample scan copied from spinet-v2's `example_scans/` (gitignored,
see backend/data/spinenet_sample/). Skipped if that data isn't present. This
is the ONE real (non-mocked) inference run the suite performs -- everything
else that touches SpineNet is stubbed (see test_full_grading.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.inference.spinenet_grading import (
    CBAM_OWNED_CONDITIONS,
    run_spinenet_grading_on_dicom_folder,
)

# backend/tests/test_spinenet_grading.py -> parents[1] == backend/
_SAMPLE_SCAN = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "spinenet_sample"
    / "t2_lumbar_scan_2"
)

_EXPECTED_CONDITIONS = {
    "pfirrmann",
    "disc_narrowing",
    "canal_stenosis",
    "spondylolisthesis",
    "upper_endplate_defect",
    "lower_endplate_defect",
    "upper_marrow",
    "lower_marrow",
    "left_foraminal",
    "right_foraminal",
    "disc_herniation",
}


@pytest.mark.skipif(
    not _SAMPLE_SCAN.exists(),
    reason="sample scan not present at data/spinenet_sample/t2_lumbar_scan_2",
)
def test_spinenet_runs_end_to_end_on_sample_scan():
    result = run_spinenet_grading_on_dicom_folder(str(_SAMPLE_SCAN))

    # Detected the lumbar vertebrae we expect from this scan.
    detected = {v["predicted_label"] for v in result.vert_dicts}
    assert {"L1", "L2", "L3", "L4", "L5", "S1"} <= detected

    # All 11 upstream conditions were produced, at every detected disc level.
    conditions = {i.condition for i in result.items}
    assert conditions == _EXPECTED_CONDITIONS
    levels = {i.level for i in result.items}
    assert "L4-L5" in levels
    assert "L5-S1" in levels

    for item in result.items:
        assert 0.0 <= item.score <= 1.0
        assert isinstance(item.severity, str) and item.severity

    # Sanity: canal/foraminal conditions ARE produced by SpineNet here (this
    # module computes them for completeness) -- it's the merge step
    # (full_grading.merge_gradings) that must discard them, not this module.
    assert CBAM_OWNED_CONDITIONS <= conditions
