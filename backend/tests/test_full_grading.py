"""Tests for the 11-label merge logic + CSV/JSON serialization.

The honesty requirement (canal/foraminal must come from the fine-tuned CBAM
model, never SpineNet) is exercised directly against `merge_gradings`: we feed
it a SpineNet result that DOES include its own canal/foraminal values (as
`run_spinenet_grading` always computes -- see `spinenet_grading.py`) and
assert they are dropped in favor of the CBAM items, even when CBAM disagrees.

Heavy inference (SpineNet detection/grading, TotalSpineSeg) is stubbed
throughout; the one real, non-mocked run lives in test_spinenet_grading.py.
"""

from __future__ import annotations

from app.inference.full_grading import (
    grading_to_csv,
    grading_to_json,
    merge_gradings,
)
from app.inference.spinenet_grading import CBAM_OWNED_CONDITIONS
from app.schemas import FullGradingResult, GradingItem


def _spinenet_item(level: str, condition: str, severity: str, score: float = 0.9) -> GradingItem:
    return GradingItem(level=level, condition=condition, severity=severity, score=score)


def _cbam_item(level: str, condition: str, severity: str, score: float = 0.5) -> GradingItem:
    return GradingItem(
        level=level, condition=condition, severity=severity, score=score, bbox=[1, 2, 3, 4, 5]
    )


def _full_spinenet_result_for_one_level(level: str) -> list[GradingItem]:
    """All 11 upstream conditions for one level, as `run_spinenet_grading`
    would produce -- including its own (deliberately different) canal/
    foraminal values, which `merge_gradings` must discard."""
    return [
        _spinenet_item(level, "pfirrmann", "Grade 3"),
        _spinenet_item(level, "disc_narrowing", "Grade 2"),
        _spinenet_item(level, "canal_stenosis", "Grade 4"),  # SpineNet's own -- must be dropped
        _spinenet_item(level, "spondylolisthesis", "None"),
        _spinenet_item(level, "upper_endplate_defect", "Absent"),
        _spinenet_item(level, "lower_endplate_defect", "Absent"),
        _spinenet_item(level, "upper_marrow", "Absent"),
        _spinenet_item(level, "lower_marrow", "Absent"),
        _spinenet_item(level, "left_foraminal", "Present"),  # SpineNet's own -- must be dropped
        _spinenet_item(level, "right_foraminal", "Absent"),  # SpineNet's own -- must be dropped
        _spinenet_item(level, "disc_herniation", "Absent"),
    ]


def test_merge_drops_spinenet_canal_and_foraminal_in_favor_of_cbam():
    """The core honesty assertion: canal/foraminal in the merged table are the
    CBAM items, verbatim -- SpineNet's own values for those conditions never
    survive the merge, even though SpineNet computed them."""
    spinenet_items = _full_spinenet_result_for_one_level("L4-L5")
    cbam_items = [
        _cbam_item("L4-L5", "canal_stenosis", "Moderate"),
        _cbam_item("L4-L5", "left_foraminal", "Severe"),
        _cbam_item("L4-L5", "right_foraminal", "Normal/Mild"),
    ]

    merged = merge_gradings(spinenet_items, cbam_items)

    by_condition = {item.condition: item for item in merged}

    # Exactly 11 conditions, one of each -- no duplicates from the drop.
    assert len(merged) == 11
    assert {item.condition for item in merged} == {i.condition for i in spinenet_items}

    # canal/foraminal are the CBAM items (identity, not just equal severity).
    for condition in CBAM_OWNED_CONDITIONS:
        assert by_condition[condition] in cbam_items
        assert by_condition[condition].bbox == [1, 2, 3, 4, 5]  # CBAM-only field

    # And specifically NOT SpineNet's own (different) severities for those 3.
    assert by_condition["canal_stenosis"].severity == "Moderate"
    assert by_condition["left_foraminal"].severity == "Severe"
    assert by_condition["right_foraminal"].severity == "Normal/Mild"

    # The other 8 conditions are untouched, straight from SpineNet.
    assert by_condition["pfirrmann"].severity == "Grade 3"
    assert by_condition["disc_herniation"].severity == "Absent"


def test_merge_keeps_cbam_items_even_without_matching_spinenet_level():
    """CBAM items for a level SpineNet didn't grade still pass through."""
    merged = merge_gradings(
        spinenet_items=[],
        cbam_items=[_cbam_item("L5-S1", "canal_stenosis", "Severe")],
    )
    assert len(merged) == 1
    assert merged[0].level == "L5-S1"
    assert merged[0].condition == "canal_stenosis"


def test_merge_produces_no_duplicate_canal_or_foraminal_conditions():
    """Sanity: even feeding two levels, only the CBAM copy of each of the 3
    CBAM-owned conditions survives per level (no leftover SpineNet duplicate)."""
    spinenet_items = _full_spinenet_result_for_one_level(
        "L4-L5"
    ) + _full_spinenet_result_for_one_level("L5-S1")
    cbam_items = [
        _cbam_item(level, condition, "Moderate")
        for level in ("L4-L5", "L5-S1")
        for condition in CBAM_OWNED_CONDITIONS
    ]

    merged = merge_gradings(spinenet_items, cbam_items)

    for level in ("L4-L5", "L5-S1"):
        for condition in CBAM_OWNED_CONDITIONS:
            matches = [
                i for i in merged if i.level == level and i.condition == condition
            ]
            assert len(matches) == 1
            assert matches[0].score == 0.5  # the CBAM item's score, not SpineNet's


def test_grading_to_csv_has_header_and_one_row_per_item():
    grading = [
        GradingItem(level="L4-L5", condition="canal_stenosis", severity="Moderate", score=0.9),
        GradingItem(level="L4-L5", condition="pfirrmann", severity="Grade 3", score=0.8),
    ]
    csv_text = grading_to_csv(grading)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "level,condition,severity,score"
    assert len(lines) == 3
    assert "L4-L5,canal_stenosis,Moderate,0.9" in lines[1]


def test_grading_to_json_round_trips_full_grading_result():
    result = FullGradingResult(
        study_id="s1",
        grading=[
            GradingItem(level="L4-L5", condition="canal_stenosis", severity="Moderate", score=0.9)
        ],
        slice_image_uri="/studies/s1/grade_full/slice.png",
        model_version="spinenet-upstream + phase2-cbam",
    )
    text = grading_to_json(result)
    reloaded = FullGradingResult.model_validate_json(text)
    assert reloaded == result
