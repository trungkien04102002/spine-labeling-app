"""Where the grading networks (SpineNet, the CBAM model) run.

Both were pinned to "cpu" because they were written on a laptop with no CUDA,
and the pin survived onto the GPU boxes: there TotalSpineSeg used the card
while the 11-label grading ran on the CPU beside it. "auto" takes the GPU when
torch can see one and the CPU otherwise, so the laptop is unchanged.
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
