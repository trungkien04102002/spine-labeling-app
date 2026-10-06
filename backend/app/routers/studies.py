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
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.export import build_export_zip
from app.jobs import jobs
from app.inference import reference_b
from app.inference.volume_io import (
    _read_image,
    MIN_SLICES,
    SKIPPED_SERIES,
    extract_dicom_zip,
    fill_missing_weighting,
    IMAGE_SUFFIXES,
    is_picture,
    picture_to_web_form,
    slice_axis,
    orientation_of,
    read_dicom_tags,
    read_metadata,
    to_web_form,
)
from app.models_db import Annotation, CorrectionLog, Patient, Reader, Series, Study
from app.routers.readers import current_reader, room_prefix
from app.schemas import (
    ActiveSeriesUpdate,
    SeriesOut,
    StudyCreate,
    StudyDetail,
    StudyUpdate,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["studies"])


BUSY_UPLOAD = (
    "This study is being graded right now. Wait until it finishes "
    "(about 1–2 minutes), then upload again."
)
BUSY_DELETE = "This study is being graded right now. Wait until it finishes, then delete it."


@router.post("/studies", status_code=201)
def create_study(
    payload: StudyCreate,
    db: Session = Depends(get_db),
    reader: Reader | None = Depends(current_reader),
) -> dict[str, object]:
    """Create a new (empty) study + its patient; a volume is uploaded later.

    In a room, the id gets the room's prefix and the patient is looked up only
    among that room's patients. Otherwise two clinicians who both type "ca1",
    or both name a patient "Nguyen Van A", would collide on one row.
    """
    study_id = payload.id if reader is None else f"{room_prefix(reader)}{payload.id}"
    if db.get(Study, study_id) is not None:
        raise HTTPException(
            status_code=409, detail=f"Study '{payload.id}' already exists."
        )
    # Group studies under one patient: reuse an existing patient of the same
    # name in the same room, otherwise create a new one.
    name = payload.patient_name.strip() or "Unknown"
    owner = reader.id if reader is not None else None
    patient = db.query(Patient).filter_by(name=name, reader_id=owner).first()
    if patient is None:
        patient = Patient(name=name, reader_id=owner)
        db.add(patient)
        db.commit()
        db.refresh(patient)
    study = Study(
        id=study_id, patient_id=patient.id, modality=payload.modality, reader_id=owner
    )
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


class ConclusionIn(BaseModel):
    text: str = Field(default="", max_length=4000)


@router.put("/studies/{study_id}/conclusion")
def save_conclusion(
    study_id: str,
    payload: ConclusionIn,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Save the clinician's own written conclusion for this study.

    Free text, beside the AI's per-level grades: what a reader would write on
    the report, including what the grade buttons cannot say. Empty clears it.
    """
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    text_value = payload.text.strip()
    study.doctor_conclusion = text_value or None
    study.doctor_conclusion_at = datetime.datetime.utcnow() if text_value else None
    db.commit()
    return {
        "text": study.doctor_conclusion,
        "saved_at": study.doctor_conclusion_at.isoformat() if study.doctor_conclusion_at else None,
    }


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
    if jobs.running_for("grade_full", study_id) is not None:
        raise HTTPException(status_code=409, detail=BUSY_DELETE)
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
        is_picture=is_picture(study.volume_path),
        doctor_conclusion=study.doctor_conclusion,
        doctor_conclusion_at=study.doctor_conclusion_at,
    )
    # Image metadata comes from the viewer NIfTI (already reoriented).
    if study.display_path and Path(study.display_path).is_file():
        meta = read_metadata(study.display_path)
        detail.dimensions = meta["dimensions"]  # type: ignore[assignment]
        detail.spacing_mm = meta["spacing_mm"]  # type: ignore[assignment]
        detail.num_slices = meta["num_slices"]  # type: ignore[assignment]
    # Acquisition tags survive only in the original DICOM (not the NIfTI).
    if study.volume_path and not detail.is_picture:
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
    # A new upload replaces the scan the running job is reading, which then
    # fails half way (2026-10-04) and leaves the old scan's mask on the new one.
    if jobs.running_for("grade_full", study_id) is not None:
        raise HTTPException(status_code=409, detail=BUSY_UPLOAD)

    study_dir = Path(settings.data_dir) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(file.filename or "volume").name
    # Accepted: DICOM series as a .zip, or a single MHA / NIfTI volume file.
    # (A bare DICOM series is a directory of slices, which HTTP upload can't
    # carry file-by-file -- zip it, that's what the .zip path is for.)
    suffixes = "".join(Path(filename).suffixes).lower()
    # .ima is how Siemens scanners name DICOM files; a single one is refused a
    # few lines on for being one slice, with advice, instead of here as an
    # "unsupported type" that sends the doctor looking for a converter.
    accepted = (".zip", ".mha", ".nii", ".nii.gz", ".dcm", ".ima") + IMAGE_SUFFIXES
    if suffixes.endswith(".mhd"):
        raise HTTPException(
            status_code=400,
            detail=(
                "A .mhd file is only a header -- its pixels are in the .raw file "
                "beside it. Put both in one .zip and upload that, or save the "
                "volume as a single .mha."
            ),
        )
    if not suffixes.endswith(accepted):
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. Upload a .zip of a DICOM series, a "
                ".mha / .nii / .nii.gz volume, or a .png / .jpg picture."
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

    # Everything already held about this study describes the PREVIOUS image:
    # the mask, the grades, the rendered slice, the converted volumes. Left
    # behind, the viewer would draw the old patient's segmentation over the new
    # scan and show grades that were never computed from it -- wrong in a way
    # that looks plausible. Clear it here rather than hoping each consumer
    # notices the image changed.
    for stale in study_dir.iterdir():
        if stale == dest:
            continue
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)

    db.query(Series).filter_by(study_id=study_id).delete()
    db.query(Annotation).filter_by(study_id=study_id).delete()
    # Corrections already handed to a training batch are not ours to retract --
    # the batch is sealed and the retraining side reasons about it. Unsubmitted
    # ones refer to grades that no longer exist, so they go.
    dropped = (
        db.query(CorrectionLog)
        .filter(
            CorrectionLog.study_id == study_id,
            CorrectionLog.batch_id.is_(None),
        )
        .delete(synchronize_session=False)
    )
    kept = (
        db.query(CorrectionLog)
        .filter(
            CorrectionLog.study_id == study_id,
            CorrectionLog.batch_id.isnot(None),
        )
        .count()
    )
    if dropped or kept:
        logger.info(
            "[upload %s] cleared %d unsubmitted correction(s); "
            "%d already in a batch were kept",
            study_id,
            dropped,
            kept,
        )
    study.analyzed_series_id = None

    # One 2D picture (PNG/JPEG): shown as a one-slice volume. Model A cannot
    # grade it -- it needs a sagittal series -- so only model B reads it, at
    # once, since that is the only answer this study can have.
    if is_picture(str(dest)):
        try:
            display = picture_to_web_form(str(dest), out_dir=str(study_dir))
        except Exception as exc:  # noqa: BLE001 - a corrupt or odd picture
            logger.error("[upload %s] picture %s would not read\n%s", study_id, filename, traceback.format_exc())
            raise HTTPException(status_code=400, detail=f"Could not read {filename} as a picture: {exc}") from exc
        row = Series(
            study_id=study_id,
            series_uid=f"image:{filename}",
            description=filename,
            orientation="image",
            volume_path=str(dest.resolve()),
            display_path=display,
            num_slices=1,
        )
        db.add(row)
        study.volume_path = row.volume_path
        study.display_path = display
        db.commit()
        logger.info("[upload %s] picture %s stored", study_id, filename)
        reference_b.run_quietly(study_id, str(dest.resolve()), study_dir)
        return {
            "study_id": study_id,
            "volume_path": study.volume_path,
            "display_path": study.display_path,
            "series_count": 1,
            "skipped": [],
        }

    # A zip that holds a volume file rather than DICOM slices -- a NIfTI zipped
    # for email, or a .mhd with its .raw -- is unwrapped and treated as that
    # file. Both were refused as "no DICOM series" before.
    if dest.suffix.lower() == ".zip":
        inner = _volume_inside_zip(dest, study_dir)
        if inner is not None:
            logger.info("[upload %s] %s holds a volume file: %s", study_id, filename, inner.name)
            dest.unlink(missing_ok=True)
            dest, filename = inner, inner.name

    skipped: list[str] = []
    if dest.suffix.lower() == ".zip":
        try:
            found = extract_dicom_zip(str(dest), str(study_dir))
            skipped = SKIPPED_SERIES.get()
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
        _refuse_single_slice(volume_path, filename)
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
        # Series left out of a DICOM archive, and why, so the page can say so
        # rather than let a missing series look like a bug.
        "skipped": skipped,
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
    out = [
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
    # Studies uploaded before the name was inferred at upload time.
    fill_missing_weighting(out)
    return out


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


_VOLUME_SUFFIXES = (".nii.gz", ".nii", ".mha", ".mhd")


def _volume_inside_zip(zip_path: Path, out_dir: Path) -> Path | None:
    """Extract and return the one volume file a zip holds, if that is all it is.

    Only when the archive has no DICOM in it at all: a DICOM export that also
    carries a stray .nii must still be read as DICOM. A .mhd comes out with its
    .raw beside it, since the header is useless alone.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/") and "__MACOSX" not in n]
            volumes = [n for n in names if n.lower().endswith(_VOLUME_SUFFIXES)]
            if len(volumes) != 1:
                return None
            others = [n for n in names if n not in volumes and not n.lower().endswith((".raw", ".zraw", ".json", ".txt"))]
            if others:
                return None  # something else in there; let the DICOM path judge it
            target = None
            for n in names:
                dst = out_dir / Path(n).name
                with zf.open(n) as src, dst.open("wb") as fh:
                    shutil.copyfileobj(src, fh)
                if n == volumes[0]:
                    target = dst
            return target
    except zipfile.BadZipFile:
        return None


def _refuse_single_slice(volume_path: str, filename: str) -> None:
    """Refuse a file that is one image rather than a volume.

    A single .dcm used to be accepted as a one-slice "study" that nothing
    downstream can segment or grade, failing much later and far from the
    cause. The fix a doctor needs is always the same, so say it here.
    """
    try:
        image = sitk.ReadImage(volume_path)
    except Exception as exc:  # noqa: BLE001 - reported as unreadable
        raise HTTPException(400, f"Could not read {filename}: {exc}") from exc
    size = image.GetSize()
    slices = size[slice_axis(image)] if len(size) == 3 else 1
    if slices < MIN_SLICES:
        raise HTTPException(
            400,
            f"{filename} is {slices} image(s), not a scan. Zip the whole series "
            f"folder -- every image of the sagittal T2 -- and upload the .zip.",
        )
