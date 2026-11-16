"""Registry of grading checkpoints and the one currently in service.

Every version is kept side by side in ``models/weights/`` and the active one is
recorded in a plain-text ``ACTIVE`` pointer, so switching is reversible. The
baseline checkpoint can be deactivated but is never overwritten or removed
here, so reverting is always possible.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

# backend/app/feedback/model_registry.py -> parents[2] == backend/
WEIGHTS_DIR = Path(__file__).resolve().parents[2] / "models" / "weights"

#: The checkpoint the app ships with; `revert()` always returns here.
BASELINE = "phase2_cbam.pth"

_POINTER = "ACTIVE"


class UnknownCheckpoint(ValueError):
    """Raised when asked to activate a checkpoint that is not on disk."""


@dataclass(frozen=True)
class CheckpointInfo:
    name: str
    size_bytes: int
    modified_at: datetime.datetime
    is_active: bool
    is_baseline: bool
    metrics: dict | None  # before/after held-out numbers, when a sidecar exists


def _pointer_path() -> Path:
    return WEIGHTS_DIR / _POINTER


def active_checkpoint_name() -> str:
    """Name of the checkpoint in service, falling back to the baseline.

    A missing or stale pointer resolves to the baseline rather than raising:
    serving the known-good model is always preferable to refusing to serve.
    """
    pointer = _pointer_path()
    if pointer.is_file():
        name = pointer.read_text().strip()
        if name and (WEIGHTS_DIR / name).is_file():
            return name
    return BASELINE


def active_checkpoint_path() -> Path:
    return WEIGHTS_DIR / active_checkpoint_name()


def _metrics_for(checkpoint: Path) -> dict | None:
    """Read the sidecar `<name>.json` written next to a retrained checkpoint.

    Metrics live in a sidecar so listing versions does not load the ~240MB
    checkpoints themselves.
    """
    sidecar = checkpoint.with_suffix(checkpoint.suffix + ".json")
    if not sidecar.is_file():
        return None
    try:
        return json.loads(sidecar.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_checkpoints() -> list[CheckpointInfo]:
    """Every `.pth` in the weights directory, baseline first then newest."""
    if not WEIGHTS_DIR.is_dir():
        return []

    active = active_checkpoint_name()
    found = []
    for path in WEIGHTS_DIR.glob("*.pth"):
        stat = path.stat()
        found.append(
            CheckpointInfo(
                name=path.name,
                size_bytes=stat.st_size,
                modified_at=datetime.datetime.fromtimestamp(stat.st_mtime),
                is_active=path.name == active,
                is_baseline=path.name == BASELINE,
                metrics=_metrics_for(path),
            )
        )
    found.sort(key=lambda c: (not c.is_baseline, -c.modified_at.timestamp()))
    return found


def activate(name: str) -> CheckpointInfo:
    """Put `name` into service and drop the cached model so it takes effect.

    Raises:
        UnknownCheckpoint: if `name` is not a `.pth` file in the weights
            directory. Path separators are rejected because the name comes
            from an HTTP request.
    """
    if "/" in name or "\\" in name or not name.endswith(".pth"):
        raise UnknownCheckpoint(f"Not a checkpoint name: {name!r}")

    target = WEIGHTS_DIR / name
    if not target.is_file():
        raise UnknownCheckpoint(f"No such checkpoint: {name}")

    _pointer_path().write_text(name)
    _invalidate_serving_model()
    return next(c for c in list_checkpoints() if c.name == name)


def revert() -> CheckpointInfo:
    """Go back to the shipped baseline. Always available."""
    return activate(BASELINE)


def _invalidate_serving_model() -> None:
    """Clear the grading module's cached model so the next call reloads.

    Imported lazily: `app.inference.grading` pulls in torch, and this module
    is imported by routers that must stay lightweight.
    """
    from app.inference.grading import _load_model

    _load_model.cache_clear()
