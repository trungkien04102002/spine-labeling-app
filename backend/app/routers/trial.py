"""Everything the trial produced, as one download.

The box a trial runs on is disposable -- destroying a Vast instance destroys
its disk -- so the results have to leave it, and they have to leave in a form
someone can open without this code: CSVs that Excel reads in Vietnamese, plus a
copy of the database for anything the CSVs did not anticipate. One button on
the operator page, no SSH.
"""

from __future__ import annotations

import csv
import datetime
import io
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.inference import reference_b
from app.models_db import CorrectionLog, Patient, Reader, Study, SurveyResponse
from app.routers.admin import require_admin
from app.survey_questions import QUESTIONS

router = APIRouter(tags=["trial"])

# Excel reads a CSV as the local code page unless it opens with a UTF-8
# byte-order mark, which turns Vietnamese into mojibake.
_BOM = "\ufeff"


def _csv(header: list[str], rows: list[list[object]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return _BOM + out.getvalue()


def _room_names(db: Session) -> dict[int, str]:
    return {r.id: r.name for r in db.query(Reader).all()}


def readers_csv(db: Session) -> str:
    rows = []
    for r in db.query(Reader).order_by(Reader.created_at).all():
        rows.append([
            r.id, r.name, r.created_at.isoformat(),
            db.query(Study).filter_by(reader_id=r.id).count(),
            db.query(CorrectionLog).filter_by(reader_id=r.id).count(),
            db.query(SurveyResponse).filter_by(reader_id=r.id).count(),
        ])
    return _csv(["room_id", "name", "joined_at", "studies", "corrections", "surveys"], rows)


def corrections_csv(db: Session) -> str:
    """One row per grade a clinician changed.

    ``before`` is the value in the version the clinician edited, which is the
    model's output only for the first edit to that cell; a second edit's
    ``before`` is the first edit's ``after``. To measure agreement with the
    model, take each cell's earliest row.
    """
    rooms = _room_names(db)
    patient_of = {
        s.id: (db.get(Patient, s.patient_id).name if s.patient_id else "")
        for s in db.query(Study).all()
    }
    rows = []
    for c in db.query(CorrectionLog).order_by(CorrectionLog.at, CorrectionLog.id).all():
        level, _, condition = c.field.partition("/")
        rows.append([
            c.id, rooms.get(c.reader_id, "") if c.reader_id else "",
            c.study_id, patient_of.get(c.study_id, ""), level, condition,
            c.old or "", c.new or "", c.at.isoformat() if c.at else "",
            c.submitted_at.isoformat() if c.submitted_at else "", c.batch_id or "",
        ])
    return _csv(
        ["id", "room", "study_id", "patient", "level", "condition", "before", "after",
         "corrected_at", "sent_at", "batch_id"],
        rows,
    )


def conclusions_csv(db: Session) -> str:
    """One row per study a clinician wrote a conclusion for."""
    rooms = _room_names(db)
    rows = []
    for s in (
        db.query(Study)
        .filter(Study.doctor_conclusion.isnot(None))
        .order_by(Study.doctor_conclusion_at)
        .all()
    ):
        patient = db.get(Patient, s.patient_id) if s.patient_id else None
        rows.append([
            rooms.get(s.reader_id, "") if s.reader_id else "", s.id,
            patient.name if patient else "", s.doctor_conclusion,
            s.doctor_conclusion_at.isoformat() if s.doctor_conclusion_at else "",
        ])
    return _csv(["room", "study_id", "patient", "conclusion", "saved_at"], rows)


def survey_csv(db: Session) -> str:
    rooms = _room_names(db)
    rows = []
    for r in db.query(SurveyResponse).order_by(SurveyResponse.submitted_at).all():
        raw = r.answers_json if isinstance(r.answers_json, dict) else {}
        answers = {int(k): v for k, v in raw.items()}
        rows.append(
            [r.id, rooms.get(r.reader_id, "") if r.reader_id else "",
             r.respondent or "", r.role or "", r.submitted_at.isoformat(),
             r.clinical_mean if r.clinical_mean is not None else ""]
            + [answers.get(q.id, "") for q in QUESTIONS]
            + [r.comment or ""]
        )
    return _csv(
        ["id", "room", "respondent", "role", "submitted_at", "clinical_mean"]
        + [f"Q{q.id}" for q in QUESTIONS]
        + ["comment"],
        rows,
    )


def questions_csv() -> str:
    """What each Q-column means, so the answers survive separation from code."""
    return _csv(
        ["question", "group", "kind", "required", "text"],
        [[f"Q{q.id}", q.group, q.kind, q.as_dict()["required"], q.text] for q in QUESTIONS],
    )


_README = """Spine labeling trial export
===========================

readers.csv           one row per room (a clinician, by the name they typed)
survey_responses.csv  one row per completed questionnaire, Q1..Qn = 1 (very
                      poor) .. 5 (very good); blank = skipped
questions.csv         the text of every Qn column
corrections.csv       one row per grade a clinician changed. "before" is the
                      model's value only on a cell's FIRST edit; for agreement
                      with the model, take the earliest row per cell.
conclusions.csv       the clinician's own written conclusion per study, if any
reference_b.csv       comparison model B's answer per study (whole image, not
                      per level): one row per label, prediction 1 = yes
spine.db              the full SQLite database, for anything the CSVs miss

The images clinicians uploaded are NOT in this file (they can be large); copy
backend/data/ off the box separately if they are needed. See DEPLOY_VAST.md.
"""


def _snapshot(db: Session) -> bytes | None:
    """A consistent copy of the live SQLite file, or None if there is none.

    sqlite3's backup API rather than a file copy: copying the file while the
    app writes can produce a torn database that will not open.
    """
    url = db.get_bind().url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    source = sqlite3.connect(Path(url.database))
    with tempfile.TemporaryDirectory() as tmp:
        target_path = Path(tmp) / "spine.db"
        target = sqlite3.connect(target_path)
        with target:
            source.backup(target)
        target.close()
        source.close()
        return target_path.read_bytes()


def reference_b_csv(settings: Settings) -> str:
    """Model B's saved answers, one row per (study, label)."""
    rows = []
    data = Path(settings.data_dir)
    for path in sorted(data.glob(f"*/{reference_b.RESULT_FILE}")):
        try:
            r = reference_b.load_result(path.parent)
        except ValueError:
            continue  # an unreadable file must not cost the whole export
        for item in r.results:
            rows.append(
                [path.parent.name, item.label, item.probability, item.prediction,
                 r.threshold, r.no_finding_override, r.slice_index, r.slice_count,
                 r.model, r.created_at]
            )
    return _csv(
        ["study_id", "label", "probability", "prediction", "threshold",
         "no_finding_override", "slice_index", "slice_count", "model", "created_at"],
        rows,
    )


@router.get("/trial/export.zip", dependencies=[Depends(require_admin)])
def export_trial(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> Response:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", _README)
        z.writestr("readers.csv", readers_csv(db))
        z.writestr("survey_responses.csv", survey_csv(db))
        z.writestr("questions.csv", questions_csv())
        z.writestr("corrections.csv", corrections_csv(db))
        z.writestr("reference_b.csv", reference_b_csv(settings))
        z.writestr("conclusions.csv", conclusions_csv(db))
        snapshot = _snapshot(db)
        if snapshot is not None:
            z.writestr("spine.db", snapshot)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="trial-export-{stamp}.zip"'},
    )
