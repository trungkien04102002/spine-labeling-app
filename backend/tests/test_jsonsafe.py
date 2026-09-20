"""Tests for `app.jsonsafe`, the one rule about numbers that are not numbers.

`retrain_head` reports NaN for a class the held-out set has no examples of --
deliberately, so the macro average can skip it instead of counting it as zero.
That value is correct as a measurement and invalid as JSON, and it reaches the
browser through two different endpoints (the checkpoint list on `/models` and
the re-training run log). Both go through this helper so neither can drift.
"""

import json
import math

from app.jsonsafe import finite_only


def test_nan_becomes_null():
    assert finite_only({"macro_f1": float("nan")}) == {"macro_f1": None}


def test_infinities_become_null_too():
    assert finite_only({"a": math.inf, "b": -math.inf}) == {"a": None, "b": None}


def test_real_numbers_and_other_types_are_left_alone():
    payload = {"f1": 0.61, "n": 12, "name": "batch-1", "ok": True, "gone": None}

    assert finite_only(payload) == payload


def test_nested_measurements_are_reached():
    """The sidecar nests its numbers under before/after; a shallow pass misses
    exactly the values that matter."""
    sanitized = finite_only(
        {"before": {"macro_f1": float("nan")}, "after": {"macro_f1": 0.5}}
    )

    assert sanitized == {"before": {"macro_f1": None}, "after": {"macro_f1": 0.5}}


def test_lists_are_reached():
    assert finite_only({"per_class": [0.1, float("nan"), 0.3]}) == {
        "per_class": [0.1, None, 0.3]
    }


def test_the_result_is_strictly_valid_json():
    """`json.dumps` accepts NaN by default; a browser never does. The point of
    the helper is that the output survives a strict encoder."""
    sanitized = finite_only({"before": {"macro_f1": float("nan")}})

    assert json.dumps(sanitized, allow_nan=False) == '{"before": {"macro_f1": null}}'


def test_nothing_to_sanitize_is_returned_unchanged():
    assert finite_only(None) is None
    assert finite_only({}) == {}
