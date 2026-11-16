"""Make metric documents safe to serialise as JSON.

`json.dumps` writes non-finite floats as `NaN`/`Infinity`, which are not valid
JSON; the browser's `JSON.parse` then rejects the whole response. Metrics are
legitimately NaN (e.g. `app.feedback.retrain_head` reports NaN for a class
absent from the held-out set so it is excluded from macro averages), so they
are converted to `null` at the API boundary rather than in the metric code.
"""

from __future__ import annotations

import math
from typing import Any


def finite_only(value: Any) -> Any:
    """Recursively replace every non-finite float with ``None``.

    Walks nested dicts, lists and tuples (tuples become lists); other values are
    returned unchanged.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: finite_only(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_only(entry) for entry in value]
    return value
