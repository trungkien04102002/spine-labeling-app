"""Inference backend interface + factory.

Two backends implement the same contract: `LocalBackend` runs the models in
this process; `RemoteVastBackend` (added later) posts to a Vast.ai server.
`get_backend` selects one from settings and is used as a FastAPI dependency.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.config import Settings
from app.schemas import InferResult


class InferenceBackend(ABC):
    @abstractmethod
    def infer(
        self,
        study_id: str,
        volume_path: str,
        grading_dir: str | None = None,
    ) -> InferResult:
        """Run segmentation + grading and assemble the results contract."""
        raise NotImplementedError


def get_backend(settings: Settings | None = None) -> InferenceBackend:
    """FastAPI dependency: pick the backend from `Settings.inference_mode`."""
    settings = settings or Settings()
    if settings.inference_mode == "vast":
        from app.inference.remote import RemoteVastBackend

        return RemoteVastBackend(settings.vast_url)

    from app.inference.local import LocalBackend

    return LocalBackend()
