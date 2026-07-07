"""Tests for RemoteVastBackend + the backend factory switch."""

import httpx

from app.config import Settings
from app.inference.base import get_backend
from app.inference.remote import RemoteVastBackend
from app.schemas import InferResult


def _stub_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/seg":
            return httpx.Response(
                200,
                json={
                    "mask_uri": "http://vast/masks/s1.nii.gz",
                    "labels": {"2": "spinal_canal", "41": "vertebrae_L1"},
                    "model_version": "remote-1",
                },
            )
        if request.url.path == "/grade":
            return httpx.Response(
                200,
                json={
                    "grading": [
                        {
                            "level": "L4-L5",
                            "condition": "canal_stenosis",
                            "severity": "Moderate",
                            "score": 0.7,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    return httpx.Client(
        base_url="http://vast", transport=httpx.MockTransport(handler)
    )


def test_remote_infer_returns_contract(tmp_path):
    vol = tmp_path / "v.mha"
    vol.write_bytes(b"dummy volume")

    backend = RemoteVastBackend("http://vast", client=_stub_client())
    result = backend.infer("s1", str(vol))

    assert isinstance(result, InferResult)
    assert result.study_id == "s1"
    assert result.segmentation.mask_uri == "http://vast/masks/s1.nii.gz"
    assert result.segmentation.labels[2] == "spinal_canal"
    assert result.grading[0].level == "L4-L5"
    assert result.model_version == "remote-1"


def test_get_backend_selects_remote_when_vast():
    backend = get_backend(Settings(inference_mode="vast", vast_url="http://vast"))
    assert isinstance(backend, RemoteVastBackend)


def test_get_backend_defaults_to_local():
    from app.inference.local import LocalBackend

    backend = get_backend(Settings(inference_mode="local"))
    assert isinstance(backend, LocalBackend)
