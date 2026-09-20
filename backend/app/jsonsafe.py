"""Making measurements safe to put on the wire.

Python is happy to carry `float("nan")` and `float("inf")` around, and
`json.dumps` writes them out as the bare tokens `NaN` and `Infinity`. Neither
is valid JSON: `JSON.parse` in the browser throws on them, and it throws on the
*whole document*, so one absent measurement inside one checkpoint's metrics
takes down the entire page that listed it -- not the number, the page.

The measurements themselves are right to be NaN. `app.feedback.retrain_head`
scores a class that has no examples in the held-out set as NaN precisely so it
can be left out of a macro average instead of being counted as a zero, which
would silently understate the model. That is the correct answer to "what is the
F1 for a class nobody held out"; it just must not be the answer that reaches
the browser. `null` is how JSON says "no value here", so that is what a
non-finite float becomes on the way out.

This lives outside `app.feedback` on purpose: the serialisation problem belongs
to the API layer, not to the maths.
"""

from __future__ import annotations

import math
from typing import Any


def finite_only(value: Any) -> Any:
    """Recursively replace every non-finite float with ``None``.

    Walks dicts and lists so it works on a whole sidecar document, not just a
    flat metrics block -- the sidecar `retrain_head` writes nests its numbers
    under ``before`` / ``after``, and a top-level-only pass would leave exactly
    the NaNs that matter untouched.

    Everything else is returned as-is; this is a sanitiser, not a serialiser.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: finite_only(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_only(entry) for entry in value]
    return value
