"""Clinician questionnaire: serve the questions, take answers, report them.

The questions are served rather than duplicated in the frontend, so there is
one place to edit them and no way for the two halves to drift apart while
answers are being collected.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_db import SurveyResponse
from app.survey_questions import (
    CLINICAL_IDS,
    GROUPS,
    QUESTIONS,
    REQUIRED_IDS,
    SCALE_LABELS,
    SCALE_MAX,
    SCALE_MIN,
    USABILITY_IDS,
    mean_of,
)

router = APIRouter()

_VALID_IDS = {q.id for q in QUESTIONS}


class SurveySubmission(BaseModel):
    answers: dict[int, int]
    respondent: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=128)
    comment: str | None = None


@router.get("/survey/questions")
def get_questions() -> dict[str, object]:
    """The questionnaire, in presentation order, with its rating scale."""
    return {
        "questions": [q.as_dict() for q in QUESTIONS],
        "groups": GROUPS,
        "scale": {
            "min": SCALE_MIN,
            "max": SCALE_MAX,
            "labels": SCALE_LABELS,
        },
    }


@router.post("/survey/responses", status_code=201)
def submit_response(
    payload: SurveySubmission, db: Session = Depends(get_db)
) -> dict[str, object]:
    """Record one clinician's answers.

    Six questions are required and the other ten may be skipped. The required
    six are the ones anybody who opened two studies can answer; the rest ask
    about one condition, or one screen, and a blank there is worth more than a
    guess. Means are taken over what was answered, so skipping costs nothing.
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
        respondent=(payload.respondent or None),
        role=(payload.role or None),
        answers_json={str(k): v for k, v in payload.answers.items()},
        comment=(payload.comment or None),
        # Kept on the row rather than recomputed later: it is what gets
        # reported, and a change to the question set would otherwise rewrite
        # numbers that have already been published.
        clinical_mean=mean_of(payload.answers, CLINICAL_IDS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "clinical_mean": row.clinical_mean}


@router.get("/survey/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, object]:
    """Aggregate for the operator page and for the report.

    Every row carries its own n and its 1-5 spread. At this sample size the
    mean alone misleads -- two clinicians at 1 and 5 average to the same 3 as
    two at 3 -- and questions differ in how many people answered them, because
    ten of the sixteen can be skipped.
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
        "comments": [
            {"at": r.submitted_at.isoformat(), "role": r.role, "text": r.comment}
            for r in rows
            if r.comment
        ],
    }
