"""Grading inference wrapper.

Runs the trained CBAM 3D-ResNet grading model (`models/grading_attention.py`,
checkpoint `models/weights/phase2_cbam.pth`) on the per-IVD `.npy` crops of a
study directory and returns a list of `GradingItem`s.

Preprocessing/loading conventions here mirror
`backend/reference/rsna_preprocessed_dataloader.py` and
`backend/reference/test_rsna_preprocessed.py`:
  - each `.npy` crop is already a preprocessed `(9, 112, 224)` float32 volume
    in `[0, 1]` — no further normalization is applied.
  - the model expects input shape `[B, 1, 9, 112, 224]` (channel dim added).
  - the RSNA head format produces a dict with three 3-class heads:
    `spinal_canal`, `left_foraminal`, `right_foraminal`; class index
    0/1/2 = Normal-Mild / Moderate / Severe.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from app.schemas import GradingItem
from models.grading_attention import GradingModelWithCBAM

# backend/app/inference/grading.py -> parents[2] == backend/
_WEIGHTS_PATH = (
    Path(__file__).resolve().parents[2] / "models" / "weights" / "phase2_cbam.pth"
)

# Model head name -> GradingItem.condition value.
_HEAD_TO_CONDITION = {
    "spinal_canal": "canal_stenosis",
    "left_foraminal": "left_foraminal",
    "right_foraminal": "right_foraminal",
}

# argmax class index -> severity label (matches severity_map in
# backend/reference/test_rsna_preprocessed.py, minus the -1/"N/A" missing-label case
# which does not apply to inference on unlabeled crops).
_SEVERITY_BY_CLASS = {0: "Normal/Mild", 1: "Moderate", 2: "Severe"}

# Matches spine level tokens like "l1", "l5", "s1" (case-insensitive).
_LEVEL_TOKEN_RE = re.compile(r"^[lsLS]\d+$")


@lru_cache(maxsize=1)
def _load_model() -> GradingModelWithCBAM:
    """Load the CBAM grading model once and cache it for the process lifetime."""
    model = GradingModelWithCBAM(format="rsna", use_cbam=True)

    checkpoint = torch.load(
        str(_WEIGHTS_PATH), map_location="cpu", weights_only=False
    )
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]
    elif isinstance(checkpoint, dict) and "model_weights" in checkpoint:
        state_dict = checkpoint["model_weights"]
    else:
        state_dict = checkpoint

    model.load_state_dict(state_dict)
    model.eval()
    return model


def _level_from_filename(npy_path: Path) -> str:
    """Derive a display level (e.g. "L4-L5") from a crop filename.

    Expected filename shape is `<series_id>_<level_token>_<level_token>.npy`,
    e.g. `238042023_l4_l5.npy` -> "L4-L5", `238042023_l5_s1.npy` -> "L5-S1".
    """
    tokens = npy_path.stem.split("_")
    level_tokens = [t for t in tokens if _LEVEL_TOKEN_RE.match(t)]
    if not level_tokens:
        # Fall back to the last two underscore-separated tokens.
        level_tokens = tokens[-2:] if len(tokens) >= 2 else tokens
    return "-".join(t.upper() for t in level_tokens)


def _grade_crop(
    model: GradingModelWithCBAM,
    volume: np.ndarray,
    level: str,
    bbox: list[float] | None = None,
) -> list[GradingItem]:
    """Grade one `(9, 112, 224)` crop -> one `GradingItem` per condition head."""
    # [9, 112, 224] -> [1, 1, 9, 112, 224] (batch, channel dims).
    tensor = torch.from_numpy(volume).float().unsqueeze(0).unsqueeze(0)
    with torch.no_grad():
        outputs = model(tensor)

    items: list[GradingItem] = []
    for head_name, condition in _HEAD_TO_CONDITION.items():
        probs = F.softmax(outputs[head_name], dim=1).squeeze(0)
        class_idx = int(torch.argmax(probs).item())
        items.append(
            GradingItem(
                level=level,
                condition=condition,
                severity=_SEVERITY_BY_CLASS[class_idx],
                score=float(probs[class_idx].item()),
                bbox=bbox,
                heatmap_uri=None,
            )
        )
    return items


def grade_crops(crops: dict[str, dict[str, object]]) -> list[GradingItem]:
    """Grade per-disc crops produced by `crops.extract_disc_crops`.

    Args:
        crops: ``{level: {"crop": np.ndarray(9,112,224), "bbox": [...]}}``.

    Returns:
        Three `GradingItem`s per disc (canal_stenosis, left/right foraminal),
        each carrying the disc's bbox for the viewer overlay.
    """
    model = _load_model()
    items: list[GradingItem] = []
    for level, data in crops.items():
        items.extend(
            _grade_crop(model, data["crop"], level, bbox=data.get("bbox"))  # type: ignore[arg-type]
        )
    return items


def run_grading(study_dir: str) -> list[GradingItem]:
    """Run the CBAM grading model on every per-IVD `.npy` crop in `study_dir`.

    Kept for RSNA-style preprocessed studies that ship `.npy` crops. The app's
    live path grades seg-localized crops via `grade_crops` instead.

    Args:
        study_dir: directory containing one or more preprocessed `(9, 112, 224)`
            float32 `.npy` crops, one per IVD level.

    Returns:
        A `GradingItem` per (level, condition) pair -- three per crop file.
    """
    model = _load_model()
    items: list[GradingItem] = []
    for npy_path in sorted(Path(study_dir).glob("*.npy")):
        volume = np.load(npy_path)
        items.extend(_grade_crop(model, volume, _level_from_filename(npy_path)))
    return items
