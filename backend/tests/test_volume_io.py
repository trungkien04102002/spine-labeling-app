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


# --- Spacing recovery when GDCM gives up ------------------------------------


def _write_anonymised_slice(path: Path, index: int, *, conformant: bool) -> None:
    """Write one DICOM slice shaped like the RSNA-2024 anonymised exports.

    Those files declare ``Enhanced MR Image Storage`` while carrying ordinary
    single-frame classic MR data. For Enhanced MR the standard puts the voxel
    size in ``SharedFunctionalGroupsSequence -> PixelMeasuresSequence``, so GDCM
    looks there, finds nothing, and returns 1x1x1 mm -- ignoring the legacy
    ``(0028,0030) PixelSpacing`` sitting in the same file, which pydicom reads
    without complaint. ``conformant=True`` writes plain MR Image Storage.
    """
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    storage = (
        pydicom.uid.MRImageStorage
        if conformant
        else pydicom.uid.EnhancedMRImageStorage
    )
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = storage
    meta.MediaStorageSOPInstanceUID = generate_uid()

    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    if conformant:
        ds.SOPClassUID = storage  # the broken exports omit it entirely
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = "1.2.3.4.5"
    ds.StudyInstanceUID = "1.2.3.4"
    ds.Modality = "MR"
    ds.Rows, ds.Columns = 8, 8
    ds.PixelSpacing = [0.46875, 0.46875]
    ds.SliceThickness = 4.0
    ds.SpacingBetweenSlices = 4.8
    # Sagittal stack: slices step along patient x.
    ds.ImageOrientationPatient = [0, 1, 0, 0, 0, -1]
    ds.ImagePositionPatient = [index * 4.8, 0.0, 0.0]
    ds.InstanceNumber = index + 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = np.full((8, 8), index, dtype=np.uint16).tobytes()
    ds.save_as(str(path), enforce_file_format=True)


def _series_dir(tmp_path: Path, *, conformant: bool) -> Path:
    directory = tmp_path / ("conformant" if conformant else "anonymised")
    directory.mkdir()
    for i in range(4):
        _write_anonymised_slice(directory / f"{i}.dcm", i, conformant=conformant)
    return directory


def test_spacing_survives_an_enhanced_mr_declaration(tmp_path):
    """The failure this guards is silent: only the mask comes out wrong.

    A lumbar series read as isotropic 1 mm is handed to TotalSpineSeg several
    times the wrong physical size, and the vertebrae come back labelled as
    cervical/thoracic. Nothing raises.
    """
    from app.inference.volume_io import _read_image

    image = _read_image(str(_series_dir(tmp_path, conformant=False)))

    x, y, z = image.GetSpacing()
    assert (round(x, 5), round(y, 5)) == (0.46875, 0.46875)
    assert z == pytest.approx(4.8)


def _raw_gdcm_spacing(directory: Path):
    """What SimpleITK returns on its own, with no recovery applied."""
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(reader.GetGDCMSeriesFileNames(str(directory)))
    return tuple(round(float(s), 5) for s in reader.Execute().GetSpacing())


def test_the_fallback_is_the_thing_being_worked_around(tmp_path):
    """Pins the premise: GDCM really does drop the spacing for these files.

    Without this the recovery test would pass even if GDCM had been reading the
    spacing correctly all along, and nobody would notice the code was dead.
    """
    assert _raw_gdcm_spacing(_series_dir(tmp_path, conformant=False)) == (
        1.0,
        1.0,
        1.0,
    )


def test_conformant_dicom_never_reaches_the_fallback(tmp_path):
    """GDCM stays the authority whenever it actually knows the answer."""
    from app.inference.volume_io import _read_image

    directory = _series_dir(tmp_path, conformant=True)
    assert _raw_gdcm_spacing(directory) != (1.0, 1.0, 1.0), (
        "conformant file should already carry its spacing"
    )

    x, y, z = _read_image(str(directory)).GetSpacing()

    assert (round(x, 5), round(y, 5)) == (0.46875, 0.46875)
    assert z == pytest.approx(4.8)


def test_slice_step_beats_slice_thickness(tmp_path):
    """4.0 mm thick but stepped 4.8 mm -- trusting SliceThickness is 20% off."""
    from app.inference.volume_io import _read_image

    image = _read_image(str(_series_dir(tmp_path, conformant=False)))

    assert image.GetSpacing()[2] != pytest.approx(4.0)
