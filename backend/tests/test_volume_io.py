"""Tests for volume I/O + web conversion.

Synthetic fixtures (a written NIfTI + MHA) always run. Tests against the real
RSNA DICOM series and SPIDER .mha are skipped when that data is absent (it lives
outside this repo).
"""

from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from app.inference.volume_io import load_volume, to_web_form

# Real datasets living in the sibling spinet-v2 checkout (gitignored, big).
_RSNA_DICOM_DIR = Path(
    "/Users/kienha/spinet-v2/rsna-2024-lumbar-spine-degenerative-classification"
    "/train_images/1132297038/2256490430"
)
_SPIDER_MHA = Path("/Users/kienha/spinet-v2/spider/images/24_t2.mha")


def _write_volume(path: Path, array: np.ndarray, spacing) -> None:
    """Write ``array`` (z, y, x) to ``path`` with the given (x, y, z) spacing."""
    image = sitk.GetImageFromArray(array)
    image.SetSpacing(spacing)
    sitk.WriteImage(image, str(path))


@pytest.fixture
def synthetic_array() -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.random((8, 16, 24)) * 255).astype(np.float32)


@pytest.mark.parametrize("ext", [".nii.gz", ".mha"])
def test_load_volume_roundtrip(tmp_path, synthetic_array, ext):
    spacing = (0.5, 0.75, 3.0)  # (x, y, z)
    vol_path = tmp_path / f"vol{ext}"
    _write_volume(vol_path, synthetic_array, spacing)

    array, out_spacing = load_volume(str(vol_path))

    assert array.shape == synthetic_array.shape
    assert np.allclose(array, synthetic_array, atol=1e-3)
    assert out_spacing == pytest.approx(spacing)


def test_to_web_form_produces_readable_nifti(tmp_path, synthetic_array):
    src = tmp_path / "vol.mha"
    _write_volume(src, synthetic_array, (1.0, 1.0, 1.0))

    web_path = to_web_form(str(src), out_dir=str(tmp_path))

    assert web_path.endswith(".nii.gz")
    assert Path(web_path).exists()
    # Re-load: same shape, valid NIfTI.
    reloaded, _ = load_volume(web_path)
    assert reloaded.shape == synthetic_array.shape


@pytest.mark.skipif(
    not _RSNA_DICOM_DIR.is_dir(), reason="RSNA DICOM sample not present"
)
def test_load_volume_rsna_dicom_series(tmp_path):
    array, spacing = load_volume(str(_RSNA_DICOM_DIR))

    assert array.ndim == 3
    assert all(s > 0 for s in array.shape)
    assert len(spacing) == 3
    assert all(s > 0 for s in spacing)

    web_path = to_web_form(str(_RSNA_DICOM_DIR), out_dir=str(tmp_path))
    assert Path(web_path).exists()
    reloaded, _ = load_volume(web_path)
    assert reloaded.shape == array.shape


@pytest.mark.skipif(
    not _SPIDER_MHA.is_file(), reason="SPIDER .mha sample not present"
)
def test_load_volume_spider_mha(tmp_path):
    array, spacing = load_volume(str(_SPIDER_MHA))

    assert array.ndim == 3
    assert all(s > 0 for s in array.shape)
    assert len(spacing) == 3

    web_path = to_web_form(str(_SPIDER_MHA), out_dir=str(tmp_path))
    assert Path(web_path).exists()
