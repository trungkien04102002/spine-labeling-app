"""Reader rooms: per-clinician workspaces entered by name plus a 4-digit PIN.

Rooms provide separation, not security: concurrent clinicians must not see or
overwrite each other's studies, grades and survey answers. Names are picked
from a list to avoid duplicate spellings; the PIN prevents opening the wrong
room. A personal link (``/?phong=<code>``, issued from /admin) also opens a
room and is the recovery path for a forgotten PIN.

The frontend sends the room id in the ``X-Reader-Id`` header. Requests
without it act as the operator view and see everything (used by /admin and
the tests).
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import logging
import re
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models_db import (
    Annotation,
    CorrectionLog,
    Patient,
    Reader,
    Series,
    Study,
    SurveyResponse,
)

from app.routers.admin import require_admin  # noqa: E402

router = APIRouter(tags=["readers"])
logger = logging.getLogger("uvicorn.error")


def reader_key(name: str) -> str:
    """Case- and spacing-insensitive identity for a typed name."""
    return re.sub(r"\s+", " ", name).strip().casefold()


def current_reader(
    x_reader_id: int | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Reader | None:
    """Return the request's room, or None for the operator view.

    An unknown room id is rejected with 401 rather than ignored, since falling
    back to the operator view would expose every room's data.
    """
    if x_reader_id is None:
        return None
    reader = db.get(Reader, x_reader_id)
    if reader is None:
        raise HTTPException(401, "This room no longer exists; please enter your name again.")
    return reader


def room_prefix(reader: Reader) -> str:
    """Prefix for study ids created in a room, so ids are unique across rooms."""
    return f"p{reader.id}-"


# Excludes 0/o and 1/l/i, which are easily confused when copied by hand.
_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def ensure_code(db: Session, reader: Reader) -> str:
    """Return the room's link code, generating it on first use."""
    if reader.code:
        return reader.code
    while True:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if db.query(Reader).filter_by(code=code).first() is None:
            break
    reader.code = code
    db.commit()
    return code


_PIN = re.compile(r"\d{4}")


def _check_pin_format(pin: str) -> str:
    pin = pin.strip()
    if not _PIN.fullmatch(pin):
        raise HTTPException(400, "The PIN must be exactly 4 digits.")
    return pin


def hash_pin(pin: str) -> str:
    """Hash a PIN with salted PBKDF2.

    A 4-digit PIN is guessable regardless; hashing only keeps the plain PIN
    out of the database and exports.
    """
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000)
    return f"{salt}${digest.hex()}"


def pin_matches(pin: str, stored: str) -> bool:
    salt, _, want = stored.partition("$")
    got = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()
    return hmac.compare_digest(got, want)


def _room_out(db: Session, reader: Reader, created: bool) -> dict[str, object]:
    return {
        "id": reader.id,
        "name": reader.name,
        "code": ensure_code(db, reader),
        "created": created,
        "has_pin": reader.pin_hash is not None,
        "studies": db.query(Study).filter_by(reader_id=reader.id).count(),
    }


class JoinIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    pin: str | None = Field(default=None, max_length=8)


@router.post("/readers")
def join(payload: JoinIn, db: Session = Depends(get_db)) -> dict[str, object]:
    """Enter a room by name, creating it if the name is new.

    A room with a PIN requires it (403 if wrong). A new room takes the PIN
    supplied, if any; rooms created without one report ``has_pin: false`` so
    the clinician sets it on first entry.
    """
    name = re.sub(r"\s+", " ", payload.name).strip()
    if not name:
        raise HTTPException(400, "Please enter a name.")
    key = reader_key(name)
    reader = db.query(Reader).filter_by(key=key).first()
    created = reader is None
    if created:
        pin = _check_pin_format(payload.pin) if payload.pin else None
        reader = Reader(name=name, key=key, pin_hash=hash_pin(pin) if pin else None)
        db.add(reader)
        db.commit()
        db.refresh(reader)
    elif reader.pin_hash is not None:
        if not payload.pin or not pin_matches(payload.pin.strip(), reader.pin_hash):
            raise HTTPException(403, "Wrong PIN.")
    return _room_out(db, reader, created)


@router.get("/readers/public")
def public_rooms(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """List room names for the sign-in page; link codes are not exposed."""
    return [
        {"id": r.id, "name": r.name, "has_pin": r.pin_hash is not None}
        for r in db.query(Reader).order_by(Reader.name).all()
    ]


@router.get("/readers/me")
def my_room(
    reader: Reader | None = Depends(current_reader),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Return the current room; 400 without an ``X-Reader-Id`` header."""
    if reader is None:
        raise HTTPException(400, "Not in a room.")
    return _room_out(db, reader, created=False)


class PinIn(BaseModel):
    pin: str = Field(max_length=8)


@router.post("/readers/me/pin")
def set_my_pin(
    payload: PinIn,
    reader: Reader | None = Depends(current_reader),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Set the PIN of a room that has none (409 if it already has one).

    Changing a PIN requires an admin reset first, so nobody can lock a
    colleague out.
    """
    if reader is None:
        raise HTTPException(400, "Not in a room.")
    if reader.pin_hash is not None:
        raise HTTPException(409, "This room already has a PIN.")
    reader.pin_hash = hash_pin(_check_pin_format(payload.pin))
    db.commit()
    return _room_out(db, reader, created=False)


@router.delete("/readers/{reader_id}/pin", dependencies=[Depends(require_admin)])
def reset_pin(reader_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """Clear a room's PIN (admin only); the next entry sets a new one."""
    reader = db.get(Reader, reader_id)
    if reader is None:
        raise HTTPException(404, f"No room {reader_id}")
    reader.pin_hash = None
    db.commit()
    return {"id": reader.id, "has_pin": False}


@router.get("/readers/code/{code}")
def enter_by_code(code: str, db: Session = Depends(get_db)) -> dict[str, object]:
    """Follow a personal link into its room."""
    reader = db.query(Reader).filter_by(code=code.strip().lower()).first()
    if reader is None:
        raise HTTPException(404, "This link does not match any room.")
    return _room_out(db, reader, created=False)


@router.get("/readers", dependencies=[Depends(require_admin)])
def list_readers(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """List all rooms with their study, correction and survey counts (admin only)."""
    out = []
    for r in db.query(Reader).order_by(Reader.created_at).all():
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "code": ensure_code(db, r),
                "has_pin": r.pin_hash is not None,
                "created_at": r.created_at.isoformat(),
                "studies": db.query(Study).filter_by(reader_id=r.id).count(),
                "corrections": db.query(CorrectionLog).filter_by(reader_id=r.id).count(),
                "surveys": db.query(SurveyResponse).filter_by(reader_id=r.id).count(),
            }
        )
    return out


def _is_sample(study_id: str, settings: Settings) -> bool:
    return any(
        fnmatch.fnmatchcase(study_id, pattern.strip())
        for pattern in settings.sample_studies.split(",")
        if pattern.strip()
    )


def _original_ai(db: Session, study_id: str) -> Annotation | None:
    return (
        db.query(Annotation)
        .filter_by(study_id=study_id, kind="ai")
        .order_by(desc(Annotation.version), desc(Annotation.id))
        .first()
    )


@router.get("/samples")
def list_samples(
    reader: Reader | None = Depends(current_reader),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, object]]:
    """List graded sample studies and whether the current room has copied each."""
    have = set()
    if reader is not None:
        prefix = room_prefix(reader)
        have = {
            s.id[len(prefix):]
            for s in db.query(Study).filter_by(reader_id=reader.id).all()
            if s.id.startswith(prefix)
        }
    out = []
    for s in db.query(Study).filter(Study.reader_id.is_(None)).order_by(Study.id).all():
        if not _is_sample(s.id, settings) or not s.volume_path:
            continue
        if _original_ai(db, s.id) is None:
            continue  # nothing graded to show, so nothing worth copying
        out.append({"id": s.id, "added": s.id in have})
    return out


def _rewrite(path: str | None, src: Path, dst: Path) -> str | None:
    """Repoint an absolute path from the sample's directory to the copy's.

    Paths are stored absolute. Rebasing on the directory, rather than
    replacing a substring of the id, keeps DEMO-001 from matching DEMO-0010.
    """
    if not path:
        return path
    p = Path(path)
    try:
        return str(dst / p.relative_to(src))
    except ValueError:
        return path  # outside the study directory; shared, leave it alone


@router.post("/readers/{reader_id}/samples/{sample_id}", status_code=201)
def add_sample(
    reader_id: int,
    sample_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Copy a sample study into a room with only its original AI grading.

    A copy (not a shared view) because grades are stored per study.
    Corrections made to the sample are not copied. Returns 404 for an unknown
    room or sample, 409 if the sample was never graded, and ``created: false``
    if the room already has it.
    """
    reader = db.get(Reader, reader_id)
    if reader is None:
        raise HTTPException(404, f"No room {reader_id}")
    src_study = db.get(Study, sample_id)
    if src_study is None or src_study.reader_id is not None or not _is_sample(sample_id, settings):
        raise HTTPException(404, f"{sample_id} is not a sample study")
    ai = _original_ai(db, sample_id)
    if ai is None:
        raise HTTPException(409, f"{sample_id} has never been graded")

    new_id = f"{room_prefix(reader)}{sample_id}"
    if db.get(Study, new_id) is not None:
        return {"id": new_id, "created": False}

    data_root = Path(settings.data_dir).resolve()
    src_dir, dst_dir = data_root / sample_id, data_root / new_id
    if src_dir.is_dir():
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)

    src_patient = db.get(Patient, src_study.patient_id)
    patient = (
        db.query(Patient)
        .filter_by(reader_id=reader.id, name=src_patient.name)
        .first()
    )
    if patient is None:
        patient = Patient(name=src_patient.name, reader_id=reader.id)
        db.add(patient)
        db.flush()

    study = Study(
        id=new_id,
        patient_id=patient.id,
        reader_id=reader.id,
        modality=src_study.modality,
        volume_path=_rewrite(src_study.volume_path, src_dir, dst_dir),
        display_path=_rewrite(src_study.display_path, src_dir, dst_dir),
    )
    db.add(study)
    db.flush()

    new_series_id: dict[int, int] = {}
    for s in db.query(Series).filter_by(study_id=sample_id).all():
        copy = Series(
            study_id=new_id,
            series_uid=s.series_uid,
            description=s.description,
            orientation=s.orientation,
            volume_path=_rewrite(s.volume_path, src_dir, dst_dir),
            display_path=_rewrite(s.display_path, src_dir, dst_dir),
            num_slices=s.num_slices,
        )
        db.add(copy)
        db.flush()
        new_series_id[s.id] = copy.id
    if src_study.analyzed_series_id in new_series_id:
        study.analyzed_series_id = new_series_id[src_study.analyzed_series_id]

    db.add(
        Annotation(
            study_id=new_id,
            version=0,
            kind="ai",
            payload_json=ai.payload_json,
            mask_path=_rewrite(ai.mask_path, src_dir, dst_dir),
        )
    )
    db.commit()
    logger.info("[room %s] copied sample %s as %s", reader.name, sample_id, new_id)
    return {"id": new_id, "created": True}
