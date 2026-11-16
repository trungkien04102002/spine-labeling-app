"""Volume I/O and conversion for the viewer and the models.

Reads a DICOM series (a directory of slices, uploaded as a ``.zip`` and split by
``extract_dicom_zip``), a MetaImage ``.mha`` or a NIfTI file via SimpleITK.
Cornerstone3D only loads NIfTI, so ``to_web_form`` always emits ``.nii.gz``.
"""

from __future__ import annotations

import dataclasses
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import contextvars
import logging
from collections import Counter

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
    """Classify the acquisition plane from the image's direction cosines.

    The dominant patient-space component of the slice normal names the plane:
    x (left-right) = sagittal, y (anterior-posterior) = coronal,
    z (superior-inferior) = axial. Oblique stacks, common for axial lumbar
    series angled to each disc, classify by their dominant component.
    """
    direction = image.GetDirection()
    if len(direction) != 9:
        return "unknown"
    stack = slice_axis(image)
    # GetDirection() is row-major; column `stack` is that axis in patient space.
    normal = (direction[stack], direction[3 + stack], direction[6 + stack])
    axis = max(range(3), key=lambda i: abs(normal[i]))
    return ("sagittal", "coronal", "axial")[axis]


def slice_axis(image: sitk.Image) -> int:
    """Return the array axis the slices are stacked along.

    A DICOM series always stacks along the last axis, but NIfTI/MetaImage files
    need not (SPIDER volumes stack sagittal slices along the first). The
    stacking axis is the most coarsely sampled one; ties (isotropic scans) go
    to the axis with fewest samples, then to the last axis.
    """
    spacing, size = image.GetSpacing(), image.GetSize()
    if len(spacing) != 3:
        return 2
    return max(range(3), key=lambda i: (round(spacing[i], 3), -size[i], i))


logger = logging.getLogger("uvicorn.error")


def describe_unreadable(directory: Path, sample: int = 3) -> str:
    """Summarise files that failed to parse as a DICOM series.

    Distinguishes non-DICOM files from valid DICOM that GDCM refuses (e.g.
    JPEG2000-compressed pixels), so a failed upload can be diagnosed from the
    log and the error message alone.
    """
    files = sorted(p for p in directory.iterdir() if p.is_file())
    exts = Counter("".join(p.suffixes).lower() or "<no extension>" for p in files)
    parts = [
        f"{len(files)} file(s)",
        "extensions: "
        + ", ".join(f"{ext} x{n}" for ext, n in exts.most_common(5)),
    ]
    for path in files[:sample]:
        # Strict read on purpose: force=True would "parse" a JPEG with empty
        # fields and hide whether the file was DICOM at all.
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True)
        except pydicom.errors.InvalidDicomError:
            parts.append(f"{path.name}: not a DICOM file")
            continue
        except Exception as exc:  # noqa: BLE001 - reporting, never re-raised
            parts.append(
                f"{path.name}: unreadable ({type(exc).__name__}: {exc})"
            )
            continue
        syntax = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
        parts.append(
            f"{path.name}: Modality={ds.get('Modality', '?')} "
            f"TransferSyntax={getattr(syntax, 'name', None) or syntax or 'missing'}"
        )
    return " | ".join(parts)


def extract_dicom_zip(zip_path: str, out_dir: str) -> list[SeriesInfo]:
    """Extract a ``.zip`` of DICOM files, split it per series, describe each.

    Series membership comes from ``SeriesInstanceUID`` in the headers, not the
    folder layout, so all files are unpacked flat first and then grouped. Each
    series lands in ``dicom/<n>_<uid>/`` because downstream readers expect one
    series per directory. Name collisions are de-duplicated, zip-slip is
    rejected, and localizers or unreadable series are skipped (see
    ``SKIPPED_SERIES``). Raises ``ValueError`` if no usable series remains.
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
    logger.info(
        "[upload] unpacked %d file(s) from %s",
        sum(1 for p in staging.iterdir() if p.is_file()),
        Path(zip_path).name,
    )

    # Group by SeriesInstanceUID (read from headers, not filenames/extensions).
    series_ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(staging))
    if not series_ids:
        diagnosis = describe_unreadable(staging)
        logger.error("[upload] no DICOM series -- %s", diagnosis)
        raise ValueError(
            f"Zip archive contains no DICOM series. Contents: {diagnosis}"
        )

    found: list[SeriesInfo] = []
    skipped: list[str] = []
    for index, uid in enumerate(series_ids):
        files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(staging), uid)
        if not files:
            continue
        # Directory name stays filesystem-safe; the real UID lives in the DB.
        series_dir = dest / f"{index}_{_safe_name(uid)}"
        series_dir.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.move(path, series_dir / Path(path).name)
        # One bad series must not fail the upload: exports can include
        # reference series of differently sized images that ITK cannot stack.
        label = _series_label(series_dir) or uid[-12:]
        reason = _not_diagnostic(series_dir, len(files))
        if reason:
            skipped.append(f"{label} ({reason})")
            shutil.rmtree(series_dir, ignore_errors=True)
            continue
        try:
            found.append(_describe_series(uid, series_dir))
        except Exception as exc:  # noqa: BLE001 - one series, reported below
            skipped.append(f"{label} (unreadable: {str(exc).splitlines()[-1][:80]})")
            shutil.rmtree(series_dir, ignore_errors=True)

    shutil.rmtree(staging, ignore_errors=True)
    if skipped:
        logger.info("[upload] skipped %d series: %s", len(skipped), "; ".join(skipped))
    if not found:
        detail = f" Skipped: {'; '.join(skipped)}." if skipped else ""
        raise ValueError(f"Zip archive contains no usable DICOM series.{detail}")
    fill_missing_weighting(found)
    found.sort(key=_reading_order)
    SKIPPED_SERIES.set(skipped)
    return found


# Series the last extract_dicom_zip call left out, for the upload endpoint to
# report. A context variable rather than a second return value, so the many
# callers that only want the series list keep working unchanged.
SKIPPED_SERIES: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "skipped_series", default=[]
)

# Scout and position-reference series are acquired to plan the scan, not to
# read it. Filtered by name because a 3-plane localizer can still stack into a
# volume ITK accepts and would otherwise be listed as a sagittal series.
_NON_DIAGNOSTIC = ("localizer", "localiser", "scout", "survey", "posdisp", "3-plane", "3plane")
MIN_SLICES = 3


def _series_label(series_dir: Path) -> str | None:
    first = next((p for p in series_dir.iterdir() if p.is_file()), None)
    if first is None:
        return None
    try:
        ds = pydicom.dcmread(str(first), stop_before_pixels=True)
    except Exception:  # noqa: BLE001
        return None
    return str(ds.get("SeriesDescription", "")).strip() or None


def _weighting_from_header(series_dir: Path) -> str | None:
    """Infer T1 / T2 / STIR from TR/TE/TI when SeriesDescription is blank.

    Anonymised exports (e.g. RSNA) often blank the description. Long TR + long
    TE is T2, short + short is T1, and an inversion time with a long TR is STIR.
    """
    first = next((p for p in series_dir.iterdir() if p.is_file()), None)
    if first is None:
        return None
    try:
        ds = pydicom.dcmread(str(first), stop_before_pixels=True)
        tr = float(ds.get("RepetitionTime") or 0)
        te = float(ds.get("EchoTime") or 0)
        ti = float(ds.get("InversionTime") or 0)
    except Exception:  # noqa: BLE001 - no timings, no guess
        return None
    if not tr or not te:
        return None
    if ti and 100 <= ti <= 250 and tr >= 1500:
        return "STIR"
    if tr >= 1500 and te >= 60:
        return "T2"
    if tr < 1000 and te < 30:
        return "T1"
    return None


def fill_missing_weighting(series: list) -> None:
    """Name an unnamed sagittal series T2 when its only sibling is a T1.

    A lumbar protocol has a sagittal T1 and a sagittal T2/STIR; the unnamed one
    beside a named T1 is the T2, which the models must read and which must sort
    first. Accepts any objects with ``description`` and ``orientation``; edits
    the list in place (frozen ``SeriesInfo`` items are replaced by copies).
    """
    sagittal = [s for s in series if s.orientation == "sagittal"]
    names = [(s.description or "").upper() for s in sagittal]
    has_t1 = any("T1" in n for n in names)
    has_t2 = any("T2" in n or "STIR" in n for n in names)
    unnamed = [s for s in sagittal if not s.description]
    if has_t1 and not has_t2 and len(unnamed) == 1:
        target = unnamed[0]
        if isinstance(target, SeriesInfo):
            series[series.index(target)] = dataclasses.replace(target, description="T2")
        else:
            target.description = "T2"


def _not_diagnostic(series_dir: Path, n_files: int) -> str | None:
    """Why a series should not be offered for reading, or None if it should."""
    if n_files < MIN_SLICES:
        return f"{n_files} image(s), too few to be a volume"
    first = next((p for p in series_dir.iterdir() if p.is_file()), None)
    try:
        ds = pydicom.dcmread(str(first), stop_before_pixels=True)
    except Exception:  # noqa: BLE001 - leave it to the reader to judge
        return None
    image_type = " ".join(str(v) for v in ds.get("ImageType", [])).lower()
    words = f"{image_type} {ds.get('SeriesDescription', '')}".lower()
    if "localizer" in image_type or any(w in words for w in _NON_DIAGNOSTIC):
        return "localizer / position reference"
    return None


def _reading_order(info: SeriesInfo) -> tuple[int, str]:
    """Sort key that puts sagittal T2/STIR first.

    The first series becomes the default active one, and the grading models
    were trained on sagittal T2; grading a T1 would silently give wrong results.
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
    if description is None:
        description = _weighting_from_header(series_dir)
    return SeriesInfo(
        series_uid=uid,
        path=str(series_dir),
        description=description,
        orientation=orientation_of(image),
        num_slices=len(files),
    )


def _slice_spacing(files: list[str], first: pydicom.Dataset) -> float | None:
    """Through-plane spacing, preferring the measured step between slices.

    ``SliceThickness`` is the excited slab, not the sampling step (RSNA lumbar
    series are 4.0 mm thick but stepped 4.8 mm), so the position delta projected
    onto the slice normal is tried first.
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

    Used only when GDCM returns its 1x1x1 mm fallback. Some anonymised exports
    (e.g. RSNA 2024) declare Enhanced MR storage but hold classic single-frame
    data, so GDCM finds no functional-group spacing and ignores the legacy
    ``PixelSpacing`` tag. Wrong spacing must be fixed here: TotalSpineSeg
    resamples by physical size and mislabels vertebrae on a mis-scaled volume.
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


# DICOM tags shown in the viewer, in display order. Public tags only;
# MHA/NIfTI sources carry none.
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

    Cornerstone's NIfTI loader makes one image per index of the third axis;
    for sagittal lumbar MRI stored slice-first it would otherwise scroll the
    wrong axis and show thin, unreadable frames.
    """
    size = image.GetSize()  # (x, y, z)
    min_axis = min(range(3), key=lambda i: size[i])
    if min_axis == 2:
        return image
    order = [i for i in range(3) if i != min_axis] + [min_axis]
    return sitk.PermuteAxes(image, order)


# Orientation every model input must arrive in (columns toward Posterior, rows
# toward Inferior, slices toward the patient's Right). This is how a DICOM
# sagittal series stacks, and therefore how the RSNA training data was laid out.
MODEL_ORIENTATION = "PIR"


def to_model_orientation(image: sitk.Image) -> sitk.Image:
    """Flip and permute a volume into the orientation the models were trained on.

    The models read raw arrays and ignore the direction matrix. DICOM series
    already arrive in MODEL_ORIENTATION; NIfTI/MetaImage files may be flipped,
    which silently swaps left and right foraminal grades. The viewer is
    unaffected because it honours the direction matrix.

    DICOMOrient only permutes and flips axes (no interpolation), so labelmaps
    stay valid.
    """
    return sitk.DICOMOrient(image, MODEL_ORIENTATION)


#: A single 2D picture (a screenshot or an exported frame) rather than a scan.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


def is_picture(path: str | None) -> bool:
    """True for a study uploaded as one 2D image instead of an MRI series."""
    return bool(path) and str(path).lower().endswith(IMAGE_SUFFIXES)


def picture_to_web_form(path: str, out_dir: str) -> str:
    """A PNG/JPEG as a one-slice grey NIfTI the viewer can show.

    No geometry survives a picture, so the spacing is 1 mm and the direction
    identity: the viewer only has to show the pixels the way they look.
    """
    from PIL import Image

    gray = np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
    image = sitk.GetImageFromArray(gray[np.newaxis, :, :])
    out_path = Path(out_dir) / f"{Path(path).stem}.nii.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(out_path))
    return str(out_path.resolve())


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
    # Write to a temp file and rename: the viewer may download the mask while
    # a grading run rewrites it, and a partial gzip fails to parse.
    tmp_path = out_path.with_name(".mask.tmp.nii.gz")
    sitk.WriteImage(image, str(tmp_path))
    tmp_path.replace(out_path)
    return str(out_path.resolve())
