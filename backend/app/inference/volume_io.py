"""Volume I/O + web conversion.

Reads the volume formats this app ingests -- a DICOM series (a directory of
``.dcm`` slices, e.g. RSNA), a MetaImage ``.mha`` (SPIDER), or a NIfTI
(``.nii`` / ``.nii.gz``) -- via SimpleITK, and standardizes them to NIfTI for
the frontend.

Cornerstone3D renders volumes through its NIfTI volume loader, so
``to_web_form`` always emits ``.nii.gz`` regardless of the source format.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import SimpleITK as sitk

_NIFTI_SUFFIXES = (".nii", ".nii.gz")


def _read_image(path: str) -> sitk.Image:
    """Read a DICOM series (directory) or a single MHA/NIfTI file."""
    src = Path(path)
    if src.is_dir():
        reader = sitk.ImageSeriesReader()
        series_files = reader.GetGDCMSeriesFileNames(str(src))
        if not series_files:
            raise FileNotFoundError(f"No DICOM series found in {src}")
        reader.SetFileNames(series_files)
        return reader.Execute()
    if not src.is_file():
        raise FileNotFoundError(f"Volume path does not exist: {src}")
    return sitk.ReadImage(str(src))


def read_metadata(path: str) -> dict[str, object]:
    """Read display-worthy volume metadata (dimensions, spacing, slice count).

    Args:
        path: a NIfTI / MHA file or DICOM series directory.

    Returns:
        A dict with ``dimensions`` (x, y, z), ``spacing_mm`` (x, y, z rounded),
        and ``num_slices`` (the size of the last/scroll axis).
    """
    image = _read_image(path)
    size = [int(s) for s in image.GetSize()]
    spacing = [round(float(s), 3) for s in image.GetSpacing()]
    return {
        "dimensions": size,
        "spacing_mm": spacing,
        "num_slices": size[2] if len(size) == 3 else size[-1],
    }


# Curated DICOM tags worth surfacing in the viewer, in display order. Only a
# DICOM source carries these; MHA/NIfTI (e.g. SPIDER) have none, so the result
# is simply empty for those. Public tags only -- RSNA/Kaggle data is anonymized.
_DICOM_TAGS: list[tuple[str, str]] = [
    ("0008|103e", "Series"),
    ("0018|0024", "Sequence"),
    ("0018|0020", "Scanning sequence"),
    ("0018|0021", "Sequence variant"),
    ("0018|0087", "Field strength (T)"),
    ("0018|0080", "TR (ms)"),
    ("0018|0081", "TE (ms)"),
    ("0018|1314", "Flip angle"),
    ("0018|0091", "Echo train length"),
    ("0018|0050", "Slice thickness (mm)"),
    ("0018|0088", "Slice spacing (mm)"),
    ("0018|0023", "Acquisition type"),
    ("0018|5100", "Patient position"),
    ("0018|0015", "Body part"),
    ("0010|1010", "Patient age"),
    ("0010|0040", "Patient sex"),
    ("0008|0020", "Study date"),
    ("0008|0070", "Manufacturer"),
]


def read_dicom_tags(path: str) -> dict[str, str]:
    """Return curated, human-labeled DICOM acquisition tags from a series.

    Reads the first slice's header. Returns ``{}`` when ``path`` is not a DICOM
    series directory (MHA/NIfTI carry none), or when no curated tag is present.
    """
    src = Path(path)
    if not src.is_dir():
        return {}
    reader = sitk.ImageSeriesReader()
    files = reader.GetGDCMSeriesFileNames(str(src))
    if not files:
        return {}
    reader.SetFileNames(files)
    reader.LoadPrivateTagsOn()
    reader.MetaDataDictionaryArrayUpdateOn()
    reader.Execute()
    tags: dict[str, str] = {}
    for key, label in _DICOM_TAGS:
        if reader.HasMetaDataKey(0, key):
            value = reader.GetMetaData(0, key).strip()
            if value:
                tags[label] = value
    return tags


def load_volume(path: str) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Load a volume to a numpy array + voxel spacing.

    Args:
        path: a DICOM series directory, or a ``.mha`` / ``.nii`` / ``.nii.gz``
            file.

    Returns:
        ``(array, spacing)`` where ``array`` is the SimpleITK ``(z, y, x)``
        numpy volume and ``spacing`` is ``(x, y, z)`` in mm.
    """
    image = _read_image(path)
    array = sitk.GetArrayFromImage(image)
    spacing = tuple(float(s) for s in image.GetSpacing())
    return array, spacing


def _web_stem(path: str) -> str:
    """Base name for the web output (drops the source extension)."""
    src = Path(path)
    if src.is_dir():
        return src.name
    name = src.name
    for suffix in _NIFTI_SUFFIXES + (".mha",):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return src.stem


def _orient_slices_last(image: sitk.Image) -> sitk.Image:
    """Permute so the fewest-slice axis is last (the axis the viewer scrolls).

    Cornerstone's NIfTI loader enumerates one image per slice along the 3rd
    axis. Sagittal-acquired lumbar MRI (RSNA/SPIDER) has few through-plane
    slices; without this, the loader would slice the wrong (high-count) axis
    and produce thin, unreadable frames.
    """
    size = image.GetSize()  # (x, y, z)
    min_axis = min(range(3), key=lambda i: size[i])
    if min_axis == 2:
        return image
    order = [i for i in range(3) if i != min_axis] + [min_axis]
    return sitk.PermuteAxes(image, order)


def to_web_form(path: str, out_dir: str) -> str:
    """Convert a volume to a Cornerstone3D-friendly NIfTI (``.nii.gz``).

    Args:
        path: source volume (DICOM series dir, ``.mha``, or NIfTI).
        out_dir: directory to write the converted NIfTI into.

    Returns:
        Absolute path to the written ``.nii.gz`` file.
    """
    image = _orient_slices_last(_read_image(path))
    out_path = Path(out_dir) / f"{_web_stem(path)}.nii.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(out_path))
    return str(out_path.resolve())


def to_web_mask(mask_path: str, out_dir: str) -> str:
    """Convert a segmentation labelmap to a viewer-aligned ``mask.nii.gz``.

    Applies the SAME ``_orient_slices_last`` permutation as ``to_web_form`` so
    the mask's slice axis lines up with the display volume, and casts to uint16
    (Cornerstone labelmaps expect integer voxels). Axis permutation preserves
    label ids exactly -- there is no resampling/interpolation.

    Args:
        mask_path: TotalSpineSeg labelmap NIfTI (original orientation).
        out_dir: study data dir; the mask is written as ``mask.nii.gz`` there.

    Returns:
        Absolute path to the written ``mask.nii.gz`` file.
    """
    image = sitk.Cast(_orient_slices_last(_read_image(mask_path)), sitk.sitkUInt16)
    out_path = Path(out_dir) / "mask.nii.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(out_path))
    return str(out_path.resolve())
