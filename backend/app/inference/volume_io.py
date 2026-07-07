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
