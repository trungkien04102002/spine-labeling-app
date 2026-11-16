"""Clinician questionnaire: serve the questions, record answers, report them.

Questions are defined only in `app.survey_questions` and served to the
frontend, so the two cannot drift apart.
"""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models_db import Reader, SurveyResponse
from app.routers.readers import current_reader
from app.survey_questions import (
    CLINICAL_IDS,
    GROUPS,
    COMPARE_PAIRS,
    MODEL_B_PAIRS,
    COMPARE,
    COMPARE_GROUP_A_ONLY,
    QUESTIONS,
    SECTION_TITLES_A_ONLY,
    SECTIONS,
    REQUIRED_IDS,
    SCALE_LABELS,
    SCALE_MAX,
    SCALE_MIN,
    USABILITY_IDS,
    mean_of,
)

from app.routers.admin import require_admin  # noqa: E402
from app.routers.reference_b import is_visible  # noqa: E402

router = APIRouter()

_VALID_IDS = {q.id for q in QUESTIONS}


class SurveySubmission(BaseModel):
    answers: dict[int, int]
    respondent: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=128)
    comment: str | None = None


@router.get("/survey/questions")
def get_questions(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """Return the questionnaire in presentation order, with its rating scale.

    Model-B items are included only while model B is visible to clinicians.
    """
    show_b = is_visible(settings)
    shown = [q for q in QUESTIONS if show_b or q.kind != "reference_b"]
    # Without model B there is no comparison, so the comparison group is
    # renamed and its items render as plain questions.
    rename = {} if show_b else {COMPARE: COMPARE_GROUP_A_ONLY}

    def group_name(g: str) -> str:
        return rename.get(g, g)

    return {
        "questions": [{**q.as_dict(), "group": group_name(q.group)} for q in shown],
        "groups": [group_name(g) for g in GROUPS if any(q.group == g for q in shown)],
        "sections": [
            {
                "title": title if show_b else SECTION_TITLES_A_ONLY.get(title, title),
                "groups": [group_name(g) for g in groups if any(q.group == g for q in shown)],
            }
            for title, groups in SECTIONS
            if any(q.group in groups for q in shown)
        ],
        # Criteria asked of both models: render A and B together.
        "pairs": [
            {"title": title, "a": a, "b": b}
            for title, a, b in COMPARE_PAIRS
        ]
        if show_b
        else [],
        # When set, the frontend sends clinicians to this external form instead.
        "form_url": settings.survey_form_url or None,
        "scale": {
            "min": SCALE_MIN,
            "max": SCALE_MAX,
            "labels": SCALE_LABELS,
        },
    }


@router.post("/survey/responses", status_code=201)
def submit_response(
    payload: SurveySubmission,
    db: Session = Depends(get_db),
    reader: Reader | None = Depends(current_reader),
) -> dict[str, object]:
    """Record one clinician's answers.

    Only `REQUIRED_IDS` must be answered; others may be skipped and means are
    taken over answered items. Returns 400 for unknown ids, out-of-range
    values or missing required answers.
    """
    unknown = sorted(set(payload.answers) - _VALID_IDS)
    if unknown:
        raise HTTPException(400, f"Unknown question id(s): {unknown}")

    out_of_range = sorted(
        qid for qid, v in payload.answers.items() if not SCALE_MIN <= v <= SCALE_MAX
    )
    if out_of_range:
        raise HTTPException(
            400, f"Answers must be {SCALE_MIN}-{SCALE_MAX}; bad: {out_of_range}"
        )

    missing = sorted(set(REQUIRED_IDS) - set(payload.answers))
    if missing:
        raise HTTPException(
            400, f"These questions are required; missing: {missing}"
        )

    row = SurveyResponse(
        reader_id=reader.id if reader is not None else None,
        # A blank name means an anonymous response; reader_id is still kept.
        respondent=(payload.respondent or None),
        role=(payload.role or None),
        answers_json={str(k): v for k, v in payload.answers.items()},
        comment=(payload.comment or None),
        # Stored rather than recomputed, so later changes to the question set
        # do not alter already reported numbers.
        clinical_mean=mean_of(payload.answers, CLINICAL_IDS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "clinical_mean": row.clinical_mean}


@router.get("/survey/mine")
def my_responses(
    db: Session = Depends(get_db),
    reader: Reader | None = Depends(current_reader),
) -> dict[str, object]:
    """Return how many responses the current reader room has submitted."""
    if reader is None:
        return {"count": 0, "last": None}
    rows = (
        db.query(SurveyResponse)
        .filter_by(reader_id=reader.id)
        .order_by(SurveyResponse.submitted_at.desc())
        .all()
    )
    return {
        "count": len(rows),
        "last": rows[0].submitted_at.isoformat() if rows else None,
    }


@router.get("/survey/summary", dependencies=[Depends(require_admin)])
def summary(db: Session = Depends(get_db)) -> dict[str, object]:
    """Aggregate survey results (admin only).

    Each question reports its answer count and full score distribution, since
    with few respondents the mean alone is misleading and optional questions
    have different counts.
    """
    rows = db.query(SurveyResponse).order_by(SurveyResponse.submitted_at).all()

    def answers_of(row: SurveyResponse) -> dict[int, int]:
        raw = row.answers_json if isinstance(row.answers_json, dict) else {}
        return {int(k): v for k, v in raw.items()}

    per_question = []
    for q in QUESTIONS:
        values = [a[q.id] for a in map(answers_of, rows) if q.id in a]
        per_question.append(
            {
                "id": q.id,
                "text": q.text,
                "kind": q.kind,
                "group": q.group,
                "required": q.kind in ("usability", "core"),
                "n": len(values),
                "mean": round(sum(values) / len(values), 2) if values else None,
                "distribution": {
                    str(v): values.count(v) for v in range(SCALE_MIN, SCALE_MAX + 1)
                },
            }
        )

    by_id = {p["id"]: p for p in per_question}

    def block_mean(ids: list[int]) -> dict[str, object]:
        answered = [by_id[i] for i in ids if by_id[i]["mean"] is not None]
        total = sum(by_id[i]["n"] for i in ids)
        return {
            "mean": round(
                sum(p["mean"] * p["n"] for p in answered) / sum(p["n"] for p in answered),
                2,
            )
            if total
            else None,
            "answers": total,
        }

    return {
        "responses": len(rows),
        "clinical": block_mean(CLINICAL_IDS),
        "usability": block_mean(USABILITY_IDS),
        "groups": [
            {
                "name": g,
                **block_mean([q.id for q in QUESTIONS if q.group == g]),
            }
            for g in GROUPS
        ],
        "questions": per_question,
        # The same criterion rated for both models, side by side.
        "model_b_comparison": [
            {
                "ours_id": ours,
                "ours_text": by_id[ours]["text"],
                "ours_mean": by_id[ours]["mean"],
                "ours_n": by_id[ours]["n"],
                "model_b_id": b,
                "model_b_text": by_id[b]["text"],
                "model_b_mean": by_id[b]["mean"],
                "model_b_n": by_id[b]["n"],
            }
            for b, ours in MODEL_B_PAIRS.items()
        ],
        "comments": [
            {"at": r.submitted_at.isoformat(), "role": r.role, "text": r.comment}
            for r in rows
            if r.comment
        ],
    }


def _answers(row: SurveyResponse) -> dict[int, int]:
    raw = row.answers_json if isinstance(row.answers_json, dict) else {}
    return {int(k): v for k, v in raw.items()}


@router.get("/survey/responses", dependencies=[Depends(require_admin)])
def list_responses(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """List individual responses, newest first (admin only)."""
    rows = (
        db.query(SurveyResponse)
        .order_by(SurveyResponse.submitted_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "reader_id": r.reader_id,
            "submitted_at": r.submitted_at.isoformat(),
            "respondent": r.respondent,
            "role": r.role,
            "clinical_mean": r.clinical_mean,
            "answers": _answers(r),
            "comment": r.comment,
        }
        for r in rows
    ]


def survey_csv(db: Session) -> str:
    """Render responses as CSV: one row per response, one column per question.

    Headers include both the question number and its text, so the file is
    self-describing.
    """
    rows = db.query(SurveyResponse).order_by(SurveyResponse.submitted_at).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["id", "submitted_at", "respondent", "role", "clinical_mean"]
        + [f"Q{q.id} {q.text}" for q in QUESTIONS]
        + ["comment"]
    )
    for r in rows:
        a = _answers(r)
        writer.writerow(
            [r.id, r.submitted_at.isoformat(), r.respondent or "", r.role or "",
             r.clinical_mean if r.clinical_mean is not None else ""]
            + [a.get(q.id, "") for q in QUESTIONS]
            + [r.comment or ""]
        )
    return out.getvalue()


# Without a UTF-8 BOM, Excel decodes CSV with the local ANSI code page and
# garbles Vietnamese text.
_UTF8_BOM = "\ufeff"


@router.get("/survey/responses.csv", dependencies=[Depends(require_admin)])
def responses_csv(db: Session = Depends(get_db)) -> Response:
    """Download all responses as a UTF-8 CSV (admin only)."""
    return Response(
        content=_UTF8_BOM + survey_csv(db),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="survey_responses.csv"'},
    )


@router.delete("/survey/responses/{response_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_response(response_id: int, db: Session = Depends(get_db)) -> Response:
    """Permanently delete one response, e.g. a test submission (admin only).

    Returns 404 if the response does not exist.
    """
    row = db.get(SurveyResponse, response_id)
    if row is None:
        raise HTTPException(404, f"No response {response_id}")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
