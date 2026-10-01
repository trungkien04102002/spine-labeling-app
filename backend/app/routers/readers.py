"""Rooms: a clinician picks their name from a list and types a 4-digit PIN.

No account. The point is separation, not security: several clinicians trying
the tool at once must not see, or quietly overwrite, each other's studies,
grades and survey answers. Typing a name each visit split one clinician into
"Minh" and "BS Minh"; a list to pick from removes the typing, and the PIN
stops a tap on the wrong name from opening a colleague's room. A personal link
(/?phong=<code>, handed out from /admin) still goes straight in -- that is
the way back for a clinician who forgot the PIN.

The frontend sends the room as an ``X-Reader-Id`` header. A request without
one is the operator's view and sees everything, which is what /admin and the
tests rely on.
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
    """The room this request acts in, or None for the operator's view.

    An id that no longer exists (the database was reset, the browser kept an
    old room) is refused rather than ignored: silently falling back to the
    operator's view would show one clinician everybody's work.
    """
    if x_reader_id is None:
        return None
    reader = db.get(Reader, x_reader_id)
    if reader is None:
        raise HTTPException(401, "This room no longer exists; please enter your name again.")
    return reader


def room_prefix(reader: Reader) -> str:
    """Prefix for study ids made in a room, so two rooms can both have "ca1"."""
    return f"p{reader.id}-"


# No 0/o, 1/l/i: a code gets read over the phone and copied by eye.
_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def ensure_code(db: Session, reader: Reader) -> str:
    """The room's link code, minted the first time anyone asks for it.

    Lazily, so rooms created before links existed get one too.
    """
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
    """Salted PBKDF2. Four digits are guessable however they are stored; this
    only keeps the PIN itself out of the database and the export zip."""
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
    """Enter a room by name, creating it the first time the name is used.

    A room with a PIN needs it. A new room takes the PIN it is created with;
    the door always sends one, while /admin creates rooms without, and the
    clinician sets theirs on first entry (``has_pin`` false tells them to).
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
    """Names to pick from at the door. No codes: a code is a way in."""
    return [
        {"id": r.id, "name": r.name, "has_pin": r.pin_hash is not None}
        for r in db.query(Reader).order_by(Reader.name).all()
    ]


@router.get("/readers/me")
def my_room(
    reader: Reader | None = Depends(current_reader),
    db: Session = Depends(get_db),
) -> dict[str, object]:
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
    """Give a PIN-less room its PIN. Changing an existing one goes through
    /admin (reset, then set again), so nobody locks a colleague out."""
    if reader is None:
        raise HTTPException(400, "Not in a room.")
    if reader.pin_hash is not None:
        raise HTTPException(409, "This room already has a PIN.")
    reader.pin_hash = hash_pin(_check_pin_format(payload.pin))
    db.commit()
    return _room_out(db, reader, created=False)


@router.delete("/readers/{reader_id}/pin", dependencies=[Depends(require_admin)])
def reset_pin(reader_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """For a clinician who forgot theirs: the room opens without a PIN until
    they enter it and choose a new one."""
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
    """Every room with what is in it, for the operator page."""
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
    """Studies a room may copy in to try the tool, and whether it already has."""
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

    Paths are stored absolute. Replacing the directory prefix, not a substring
    of the id, is what keeps DEMO-001 from also matching DEMO-0010.
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
    """Copy one sample study into a room, as the model originally graded it.

    A copy rather than a shared view, because grades are stored per study:
    two clinicians correcting one shared study would each see the other's
    edits appear in their table. Only the model's own output comes across --
    none of the corrections anyone has made to the sample since -- so every
    clinician starts from exactly what the AI said.
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
