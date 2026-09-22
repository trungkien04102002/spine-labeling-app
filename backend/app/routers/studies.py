"""Study endpoints: uploading a volume and converting it for the viewer."""

from __future__ import annotations

import datetime
import logging
import shutil
import traceback
import zipfile
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.export import build_export_zip
from app.inference.volume_io import (
    _read_image,
    extract_dicom_zip,
    orientation_of,
    read_dicom_tags,
    read_metadata,
    to_web_form,
)
from app.models_db import Annotation, CorrectionLog, Patient, Series, Study
from app.schemas import (
    ActiveSeriesUpdate,
    SeriesOut,
    StudyCreate,
    StudyDetail,
    StudyUpdate,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["studies"])


@router.post("/studies", status_code=201)
def create_study(
    payload: StudyCreate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Create a new (empty) study + its patient; a volume is uploaded later."""
    if db.get(Study, payload.id) is not None:
        raise HTTPException(
            status_code=409, detail=f"Study '{payload.id}' already exists."
        )
    # Group studies under one patient: reuse an existing patient of the same
    # name, otherwise create a new one.
    name = payload.patient_name.strip() or "Unknown"
    patient = db.query(Patient).filter_by(name=name).first()
    if patient is None:
        patient = Patient(name=name)
        db.add(patient)
        db.commit()
        db.refresh(patient)
    study = Study(id=payload.id, patient_id=patient.id, modality=payload.modality)
    db.add(study)
    db.commit()
    return {"id": study.id, "patient_id": patient.id}


@router.patch("/studies/{study_id}")
def update_study(
    study_id: str,
    payload: StudyUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Edit a study's modality and/or its patient's name."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if payload.modality is not None:
        study.modality = payload.modality
    if payload.patient_name is not None:
        patient = db.get(Patient, study.patient_id)
        if patient is not None:
            patient.name = payload.patient_name.strip() or patient.name
    db.commit()
    return {"id": study.id, "modality": study.modality}


@router.delete("/studies/{study_id}", status_code=204)
def delete_study(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete a study, its annotations/logs, and its files on disk."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    db.query(Annotation).filter_by(study_id=study_id).delete()
    db.query(CorrectionLog).filter_by(study_id=study_id).delete()
    db.query(Series).filter_by(study_id=study_id).delete()
    db.delete(study)
    db.commit()
    shutil.rmtree(Path(settings.data_dir) / study_id, ignore_errors=True)
    return Response(status_code=204)


@router.get("/studies/{study_id}", response_model=StudyDetail)
def get_study_detail(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StudyDetail:
    """Return study + patient + image metadata for the viewer header."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    patient = db.get(Patient, study.patient_id)

    detail = StudyDetail(
        id=study.id,
        patient_id=study.patient_id,
        patient_name=patient.name if patient else "unknown",
        modality=study.modality,
        created_at=study.created_at,
        has_volume=bool(study.volume_path),
        has_mask=(Path(settings.data_dir) / study_id / "mask.nii.gz").is_file(),
    )
    # Image metadata comes from the viewer NIfTI (already reoriented).
    if study.display_path and Path(study.display_path).is_file():
        meta = read_metadata(study.display_path)
        detail.dimensions = meta["dimensions"]  # type: ignore[assignment]
        detail.spacing_mm = meta["spacing_mm"]  # type: ignore[assignment]
        detail.num_slices = meta["num_slices"]  # type: ignore[assignment]
    # Acquisition tags survive only in the original DICOM (not the NIfTI).
    if study.volume_path:
        detail.dicom_tags = read_dicom_tags(study.volume_path)
    return detail


@router.post("/studies/{study_id}/upload")
def upload_study(
    study_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Store an uploaded volume, convert it to a viewer NIfTI, record paths.

    The study row must already exist (created via demo import / patient flow).
    """
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")

    study_dir = Path(settings.data_dir) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(file.filename or "volume").name
    # Accepted: DICOM series as a .zip, or a single MHA / NIfTI volume file.
    # (A bare DICOM series is a directory of slices, which HTTP upload can't
    # carry file-by-file -- zip it, that's what the .zip path is for.)
    suffixes = "".join(Path(filename).suffixes).lower()
    accepted = (".zip", ".mha", ".nii", ".nii.gz")
    if not (suffixes.endswith(accepted) or filename.lower().endswith(".dcm")):
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. Upload a .zip of a DICOM series, or a "
                ".mha / .nii / .nii.gz volume."
            ),
        )

    dest = study_dir / filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    # Logged before anything can fail: when a doctor's study will not open, the
    # first question is always what they actually sent, and the upload is the
    # only place that knows. The file itself stays on disk for postmortem.
    logger.info(
        "[upload %s] received %s (%.1f MB, content-type %s)",
        study_id,
        filename,
        dest.stat().st_size / 1048576,
        file.content_type or "unset",
    )

    # Replace any previous upload's series rows for this study.
    db.query(Series).filter_by(study_id=study_id).delete()
    study.analyzed_series_id = None

    if dest.suffix.lower() == ".zip":
        try:
            found = extract_dicom_zip(str(dest), str(study_dir))
        except (ValueError, zipfile.BadZipFile) as exc:
            logger.error("[upload %s] %s rejected: %s", study_id, filename, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - unknown formats reach here
            # Anything not anticipated would otherwise surface as a bare 500
            # with no trace of which file caused it, on a machine nobody is
            # watching. Keep the traceback; hand back something answerable.
            logger.error(
                "[upload %s] %s failed to unpack\n%s",
                study_id,
                filename,
                traceback.format_exc(),
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not read {filename}: {type(exc).__name__}: {exc}"
                ),
            ) from exc
        logger.info(
            "[upload %s] %d series: %s",
            study_id,
            len(found),
            "; ".join(
                f"{i.description or '(no description)'} "
                f"[{i.orientation}, {i.num_slices} slices]"
                for i in found
            ),
        )
        rows = [
            Series(
                study_id=study_id,
                series_uid=info.series_uid,
                description=info.description,
                orientation=info.orientation,
                volume_path=str(Path(info.path).resolve()),
                num_slices=info.num_slices,
            )
            for info in found
        ]
    else:
        # MHA/NIfTI carry no series concept: the file is the one "series".
        volume_path = str(dest.resolve())
        rows = [
            Series(
                study_id=study_id,
                series_uid=f"file:{filename}",
                description=filename,
                orientation=_orientation_of_file(volume_path),
                volume_path=volume_path,
            )
        ]

    for row in rows:
        db.add(row)
    db.flush()  # assign row ids

    # The first row is the default active series (sagittal first, see
    # extract_dicom_zip) -- only it needs a display volume built up front;
    # the others are converted lazily when the user switches to them.
    active = rows[0]
    try:
        active.display_path = to_web_form(
            active.volume_path, out_dir=str(study_dir)
        )
    except Exception as exc:  # noqa: BLE001 - conversion, not validation
        # Reached when a series parses but will not convert (odd geometry,
        # single slice, unsupported pixel format). Distinguishing this from a
        # failed unpack is the whole point of logging both separately.
        logger.error(
            "[upload %s] %s unpacked but would not convert\n%s",
            study_id,
            filename,
            traceback.format_exc(),
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Series read, but could not be converted for viewing: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc
    study.volume_path = active.volume_path
    study.display_path = active.display_path
    db.commit()

    return {
        "study_id": study_id,
        "volume_path": study.volume_path,
        "display_path": study.display_path,
        "series_count": len(rows),
    }


def _orientation_of_file(path: str) -> str:
    """Best-effort acquisition plane for a single-file volume (MHA/NIfTI)."""
    try:
        return orientation_of(_read_image(path))
    except Exception:  # noqa: BLE001 - orientation is cosmetic, never fatal
        return "unknown"


@router.get("/studies/{study_id}/series", response_model=list[SeriesOut])
def list_series(
    study_id: str,
    db: Session = Depends(get_db),
) -> list[SeriesOut]:
    """List every acquisition in the study, for the viewer's series picker."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    rows = db.query(Series).filter_by(study_id=study_id).order_by(Series.id).all()
    return [
        SeriesOut(
            id=row.id,
            series_uid=row.series_uid,
            description=row.description,
            orientation=row.orientation,
            num_slices=row.num_slices,
            is_active=row.volume_path == study.volume_path,
            analyzed_by_ai=row.id == study.analyzed_series_id,
        )
        for row in rows
    ]


@router.put("/studies/{study_id}/active_series", response_model=list[SeriesOut])
def set_active_series(
    study_id: str,
    payload: ActiveSeriesUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[SeriesOut]:
    """Switch which acquisition the viewer (and the next AI run) works on."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    row = db.get(Series, payload.series_id)
    if row is None or row.study_id != study_id:
        raise HTTPException(
            status_code=404,
            detail=f"Series {payload.series_id} does not belong to study {study_id}.",
        )

    if not row.display_path or not Path(row.display_path).is_file():
        study_dir = Path(settings.data_dir) / study_id
        row.display_path = to_web_form(row.volume_path, out_dir=str(study_dir))

    study.volume_path = row.volume_path
    study.display_path = row.display_path
    db.commit()
    return list_series(study_id, db)


# The `.nii.gz` suffix is load-bearing: the Cornerstone NIfTI loader decides
# whether to gunzip by whether the URL path ends in ".gz".
@router.get("/studies/{study_id}/display.nii.gz")
def get_display_volume(
    study_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve the study's viewer NIfTI so the browser (Cornerstone3D) can load it."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.display_path or not Path(study.display_path).is_file():
        raise HTTPException(status_code=404, detail="No display volume for study.")
    return FileResponse(
        study.display_path,
        media_type="application/gzip",
        filename=f"{study_id}.nii.gz",
    )


# Same `.nii.gz` suffix rule as the display volume (Cornerstone gunzips on it).
@router.get("/studies/{study_id}/mask.nii.gz")
def get_mask_volume(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve the study's segmentation labelmap (written by ``/infer``)."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    mask_path = Path(settings.data_dir) / study_id / "mask.nii.gz"
    if not mask_path.is_file():
        raise HTTPException(
            status_code=404, detail="No segmentation mask; run inference first."
        )
    return FileResponse(
        str(mask_path),
        media_type="application/gzip",
        filename=f"{study_id}_mask.nii.gz",
        # The mask changes when a doctor saves edits; never serve a stale copy.
        headers={"Cache-Control": "no-store"},
    )


#: Where superseded labelmaps are kept, inside the study's own data directory.
MASK_VERSIONS_DIR = "mask_versions"


def _archive_current_mask(db: Session, study_id: str, mask_path: Path) -> str | None:
    """Keep the labelmap that is about to be overwritten, and say where it went.

    Grade corrections have always been versioned -- every edit is a new
    ``annotations`` row and the previous one is still there -- while a mask
    edit wrote straight over ``mask.nii.gz`` and destroyed what it replaced. A
    stray brush stroke saved by accident was therefore unrecoverable, and the
    traceability this tool claims held for only half of what a doctor can
    change.

    The fix is deliberately the small one: the serving path
    (``GET /studies/{id}/mask.nii.gz``, the viewer, the export) still finds the
    current mask exactly where it always did. Only the *old* bytes move, into
    ``<study>/mask_versions/``, and the annotation rows that referred to them
    are repointed there -- so each version's ``mask_path`` names the file that
    actually holds that version's mask, which is what the column was for.

    Every version is kept. A labelmap is a few hundred KB to a few MB gzipped,
    so a study edited ten times costs single-digit megabytes; pruning would
    trade the one property this exists to provide against disk that is not
    scarce.

    Returns the archive's filename (not its full path -- the on-disk layout
    stays internal), or None when there was no mask to keep.
    """
    if not mask_path.is_file():
        return None

    versions_dir = mask_path.parent / MASK_VERSIONS_DIR
    versions_dir.mkdir(parents=True, exist_ok=True)
    # Sequence number for reading order, timestamp so two saves in one second
    # cannot collide and so the file is self-describing outside the database.
    sequence = len(list(versions_dir.glob("mask_v*.nii.gz"))) + 1
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    archive = versions_dir / f"mask_v{sequence:03d}_{stamp}.nii.gz"
    shutil.copy2(mask_path, archive)

    live = mask_path.resolve()
    for row in db.query(Annotation).filter_by(study_id=study_id).all():
        if row.mask_path and Path(row.mask_path).resolve() == live:
            row.mask_path = str(archive.resolve())
    db.commit()
    return archive.name


def _record_mask_version(db: Session, study_id: str, mask_path: Path) -> int | None:
    """Add the annotation version that the just-written mask belongs to.

    Carries the latest payload forward unchanged -- a mask edit is not a grade
    edit -- so the row says "at this version, the grades were these and the
    mask was this file". It also keeps the newest row pointing at the live
    mask, which is what ``build_dataset`` reads when it re-crops discs; without
    it, repointing the old rows would have quietly aimed re-training at a
    superseded labelmap.

    Returns the new version number, or None when the study has no annotation
    yet (nothing has been inferred, so there is no version line to extend).
    """
    prior = (
        db.query(Annotation)
        .filter_by(study_id=study_id)
        .order_by(desc(Annotation.version), desc(Annotation.id))
        .first()
    )
    if prior is None:
        return None

    version = prior.version + 1
    db.add(
        Annotation(
            study_id=study_id,
            version=version,
            kind="mask",
            payload_json=dict(prior.payload_json or {}),
            mask_path=str(mask_path.resolve()),
        )
    )
    db.commit()
    return version


@router.put("/studies/{study_id}/mask")
async def save_mask(
    study_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Persist a doctor-edited labelmap (raw uint8 voxels, display geometry).

    The frontend sends the edited Cornerstone labelmap as a flat little-endian
    uint8 buffer in slice order (z, y, x); we reshape it to the display volume's
    size, copy that volume's geometry, and overwrite ``mask.nii.gz``.
    """
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.display_path or not Path(study.display_path).is_file():
        raise HTTPException(status_code=400, detail="Study has no display volume.")

    raw = await request.body()
    display = sitk.ReadImage(study.display_path)
    x, y, z = display.GetSize()  # (x, y, z)
    expected = x * y * z
    arr = np.frombuffer(raw, dtype=np.uint8)
    if arr.size != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Mask size {arr.size} != expected {expected} ({z}x{y}x{x}).",
        )

    mask_img = sitk.GetImageFromArray(arr.reshape((z, y, x)).astype(np.uint16))
    mask_img.CopyInformation(display)
    mask_path = Path(settings.data_dir) / study_id / "mask.nii.gz"
    mask_path.parent.mkdir(parents=True, exist_ok=True)

    archived = _archive_current_mask(db, study_id, mask_path)
    sitk.WriteImage(mask_img, str(mask_path))
    version = _record_mask_version(db, study_id, mask_path)

    return {
        "ok": True,
        "shape": [z, y, x],
        # What the save can be undone back to, and the annotation version this
        # edit became. Both are null on the first save of a study, when there
        # was nothing to keep.
        "previous_mask": archived,
        "version": version,
    }


@router.get("/studies/{study_id}/export")
def export_study(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Export the latest annotation as a zip (original + mask + grades + PNG)."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    ann = (
        db.query(Annotation)
        .filter_by(study_id=study_id)
        .order_by(desc(Annotation.version), desc(Annotation.id))
        .first()
    )
    if ann is None:
        raise HTTPException(
            status_code=404, detail="No annotation to export; run inference first."
        )

    mask_path = Path(settings.data_dir) / study_id / "mask.nii.gz"
    zip_bytes = build_export_zip(
        study.display_path, str(mask_path), ann.payload_json
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{study_id}_export.zip"'
        },
    )
