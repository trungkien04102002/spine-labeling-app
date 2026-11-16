"""Device selection for the grading networks (SpineNet and the CBAM model).

"auto" uses the GPU when torch can see one and the CPU otherwise.
"""

from __future__ import annotations

import torch

from app.config import Settings


def grading_device(settings: Settings | None = None) -> str:
    wanted = (settings or Settings()).grading_device
    if wanted == "auto":
        # An explicit index: SpineNet calls torch.cuda.set_device on it.
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    return wanted
