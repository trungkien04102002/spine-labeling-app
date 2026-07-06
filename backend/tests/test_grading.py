import re
from pathlib import Path

import pytest

from app.inference.grading import run_grading

# backend/tests/test_grading.py -> parents[2] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_STUDY_DIR = _REPO_ROOT / "data" / "demo_416503281"

_VALID_SEVERITIES = {"Normal/Mild", "Moderate", "Severe"}
_LEVEL_RE = re.compile(r"^[Ll]\d-.+")


@pytest.mark.skipif(
    not _DEMO_STUDY_DIR.exists(), reason="demo data not present at data/demo_416503281"
)
def test_run_grading_on_demo_study():
    items = run_grading(str(_DEMO_STUDY_DIR))

    assert isinstance(items, list)
    assert len(items) >= 3

    for item in items:
        assert item.severity in _VALID_SEVERITIES
        assert _LEVEL_RE.match(item.level), f"unexpected level format: {item.level}"
        assert 0.0 <= item.score <= 1.0
