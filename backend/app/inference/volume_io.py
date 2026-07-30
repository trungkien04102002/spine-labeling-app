"""Volume I/O + web conversion.

Reads the volume formats this app ingests -- a DICOM series (a directory of
``.dcm`` slices, e.g. RSNA, uploaded as a ``.zip`` and unpacked by
``extract_dicom_zip``), a MetaImage ``.mha`` (SPIDER), or a NIfTI
(``.nii`` / ``.nii.gz``) -- via SimpleITK, and standardizes them to NIfTI for
the frontend.

Cornerstone3D renders volumes through its NIfTI volume loader, so
``to_web_form`` always emits ``.nii.gz`` regardless of the source format.
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pydicom
import SimpleITK as sitk

_NIFTI_SUFFIXES = (".nii", ".nii.gz")

# What GDCM hands back when it cannot work out a series' real voxel size.
_FALLBACK_SPACING = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class SeriesInfo:
    """One DICOM series found inside an uploaded archive."""

    series_uid: str
    path: str  # directory holding exactly this series' slices
    description: str | None
    orientation: str  # "sagittal" | "axial" | "coronal" | "unknown"
    num_slices: int


def orientation_of(image: sitk.Image) -> str:
    """Classify an acquisition plane from the image's direction cosines.

    The slice normal is the third column of the direction matrix (the axis we
    scroll along). Its dominant patient axis names the plane: x = left-right
    normal = sagittal, y = anterior-posterior = coronal, z = superior-inferior
    = axial. Oblique acquisitions (very common for axial lumbar stacks angled
    to each disc) still classify by their dominant component, which is what a
    radiologist would call them.
    """
    direction = image.GetDirection()
    if len(direction) != 9:
        return "unknown"
    # GetDirection() is row-major; its third column is the slice normal.
    normal = (direction[2], direction[5], direction[8])
    axis = max(range(3), key=lambda i: abs(normal[i]))
    return ("sagittal", "coronal", "axial")[axis]


def extract_dicom_zip(zip_path: str, out_dir: str) -> list[SeriesInfo]:
    """Extract a ``.zip`` of DICOM files, split it per series, describe each.

    A study archive may hold several acquisitions (sagittal T1, sagittal T2,
    axial T2 ...). Series membership is decided by ``SeriesInstanceUID`` in the
    file headers, not by folder layout, so every file is unpacked first and
    then grouped. Each series lands in its own ``dicom/<n>_<uid>/`` directory,
    which keeps every downstream reader (which expects "a directory holding one
    series") working unchanged.

    Accepts flat zips (``*.dcm`` at the archive root, Oxford-demo style) and
    nested ones. Filenames are flattened, but collisions between series (both
    holding ``1.dcm``) are de-duplicated rather than silently overwritten.
    Guards against zip-slip. Raises ``ValueError`` if no DICOM series is found.
    """
    dest = Path(out_dir) / "dicom"
    if dest.exists():
        shutil.rmtree(dest)
    staging = dest / "_all"
    staging.mkdir(parents=True, exist_ok=True)
    staging_root = staging.resolve()

    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            name = Path(member.filename).name  # flatten; also neutralizes paths
            if not name or name.startswith("."):
                continue  # skip __MACOSX/.DS_Store cruft
            target = (staging / name).resolve()
            if not str(target).startswith(str(staging_root)):
                raise ValueError(f"Unsafe zip entry: {member.filename}")
            # Two series can both carry "1.dcm" -- keep both.
            if target.exists():
                stem, suffix = Path(name).stem, "".join(Path(name).suffixes)
                n = 1
                while target.exists():
                    target = staging / f"{stem}__{n}{suffix}"
                    n += 1
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)

    if not any(p.is_file() for p in staging.iterdir()):
        raise ValueError("Zip archive contains no readable files.")

    # Group by SeriesInstanceUID (read from headers, not filenames/extensions).
    series_ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(staging))
    if not series_ids:
        raise ValueError("Zip archive contains no DICOM series.")

    found: list[SeriesInfo] = []
    for index, uid in enumerate(series_ids):
        files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(staging), uid)
        if not files:
            continue
        # Directory name stays filesystem-safe; the real UID lives in the DB.
        series_dir = dest / f"{index}_{_safe_name(uid)}"
        series_dir.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.move(path, series_dir / Path(path).name)
        found.append(_describe_series(uid, series_dir))

    shutil.rmtree(staging, ignore_errors=True)
    if not found:
        raise ValueError("Zip archive contains no DICOM series.")
    found.sort(key=_reading_order)
    return found


def _reading_order(info: SeriesInfo) -> tuple[int, str]:
    """Sort key putting the series the models read first.

    Sagittal T2 leads: it is the sequence the grading models were trained on
    (and the one a radiologist opens first), so it becomes the default active
    series. Grading a study on sagittal T1 by accident would silently feed the
    models the wrong sequence.
    """
    description = (info.description or "").upper()
    if info.orientation == "sagittal":
        rank = 0 if "T2" in description or "STIR" in description else 1
    elif info.orientation == "axial":
        rank = 2
    else:
        rank = 3
    return (rank, info.series_uid)


def _safe_name(uid: str) -> str:
    """Shorten a DICOM UID into a filesystem-safe directory name."""
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in uid)
    return cleaned[-40:] or "series"


def _describe_series(uid: str, series_dir: Path) -> SeriesInfo:
    """Read one series' header/geometry to label it for the viewer."""
    reader = sitk.ImageSeriesReader()
    files = reader.GetGDCMSeriesFileNames(str(series_dir))
    reader.SetFileNames(files)
    reader.MetaDataDictionaryArrayUpdateOn()
    image = reader.Execute()
    description = None
    if reader.HasMetaDataKey(0, "0008|103e"):  # SeriesDescription
        description = reader.GetMetaData(0, "0008|103e").strip() or None
    return SeriesInfo(
        series_uid=uid,
        path=str(series_dir),
        description=description,
        orientation=orientation_of(image),
        num_slices=len(files),
    )


def _slice_spacing(files: list[str], first: pydicom.Dataset) -> float | None:
    """Through-plane spacing, preferring the distance the slices actually moved.

    ``SliceThickness`` is the excited slab, not the sampling step -- the RSNA
    lumbar series here are 4.0 mm thick but stepped 4.8 mm, a 20% error if the
    tag is trusted. Projecting the position delta onto the slice normal gives
    the real step, so that is tried first.
    """
    if len(files) > 1:
        try:
            second = pydicom.dcmread(files[1], stop_before_pixels=True)
            start = np.asarray(first.ImagePositionPatient, dtype=float)
            nxt = np.asarray(second.ImagePositionPatient, dtype=float)
            orient = np.asarray(first.ImageOrientationPatient, dtype=float)
            normal = np.cross(orient[:3], orient[3:])
            step = abs(float(np.dot(nxt - start, normal)))
            if step > 1e-3:
                return step
        except Exception:
            pass  # fall through to the header tags
    for tag in ("SpacingBetweenSlices", "SliceThickness"):
        value = getattr(first, tag, None)
        if value:
            return float(value)
    return None


def _spacing_from_headers(files: list[str]) -> tuple[float, float, float] | None:
    """Recover voxel spacing from the DICOM headers, or None if unavailable.

    Only used when GDCM already gave up. The RSNA-2024 DICOMs are anonymised
    re-exports that declare ``Enhanced MR Image Storage`` while holding ordinary
    single-frame classic MR data. For Enhanced MR the standard keeps the voxel
    size in ``SharedFunctionalGroupsSequence -> PixelMeasuresSequence``, so GDCM
    correctly looks there, finds nothing, and returns 1x1x1 mm -- ignoring the
    legacy ``(0028,0030) PixelSpacing`` that is right there in the file, and
    that pydicom reads without complaint.

    Nothing downstream notices on its own. The viewer merely looks a little
    squashed, but TotalSpineSeg resamples by *physical* size: a lumbar scan that
    claims to be isotropic 1 mm when it is really 0.47 x 0.47 x 4.8 mm arrives
    at the network several times the wrong shape, and comes back with the
    vertebrae labelled as cervical and thoracic.
    """
    try:
        first = pydicom.dcmread(files[0], stop_before_pixels=True)
    except Exception:
        return None
    pixel_spacing = getattr(first, "PixelSpacing", None)
    if pixel_spacing is None or len(pixel_spacing) != 2:
        return None
    # DICOM PixelSpacing is (row, column) = (y, x); SimpleITK wants (x, y, z).
    row, column = float(pixel_spacing[0]), float(pixel_spacing[1])
    through_plane = _slice_spacing(files, first)
    if through_plane is None:
        return None
    return (column, row, through_plane)


def _read_image(path: str) -> sitk.Image:
    """Read a DICOM series (directory) or a single MHA/NIfTI file."""
    src = Path(path)
    if src.is_dir():
        reader = sitk.ImageSeriesReader()
        series_files = reader.GetGDCMSeriesFileNames(str(src))
        if not series_files:
            raise FileNotFoundError(f"No DICOM series found in {src}")
        reader.SetFileNames(series_files)
        image = reader.Execute()
        # Trust GDCM unless it returned its "I don't know" answer verbatim.
        if tuple(round(s, 6) for s in image.GetSpacing()) == _FALLBACK_SPACING:
            recovered = _spacing_from_headers(list(series_files))
            if recovered is not None and recovered != _FALLBACK_SPACING:
                image.SetSpacing(recovered)
        return image
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
