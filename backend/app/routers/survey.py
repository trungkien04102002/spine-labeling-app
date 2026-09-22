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
    DOMAIN_IDS,
    QUESTIONS,
    SCALE_LABELS,
    SCALE_MAX,
    SCALE_MIN,
    SUS_IDS,
    sus_score,
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

    Every SUS item is required: the score is only comparable to published
    means when all ten are answered, and a partial set silently scores lower
    because unanswered items cannot contribute. The five tool-specific items
    are optional -- a clinician who never edited a mask should be able to skip
    question 13 rather than invent an answer.
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

    missing = sorted(set(SUS_IDS) - set(payload.answers))
    if missing:
        raise HTTPException(
            400,
            "The ten usability questions must all be answered for the score to "
            f"mean anything; missing: {missing}",
        )

    row = SurveyResponse(
        respondent=(payload.respondent or None),
        role=(payload.role or None),
        answers_json={str(k): v for k, v in payload.answers.items()},
        comment=(payload.comment or None),
        sus_score=sus_score(payload.answers),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "sus_score": row.sus_score}


@router.get("/survey/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, object]:
    """Aggregate for the operator page and for the report.

    Reports the per-question mean and the count behind it, because with a
    handful of clinicians the count is as important as the mean and a figure
    quoting one without the other is not honest.
    """
    rows = db.query(SurveyResponse).order_by(SurveyResponse.submitted_at).all()
    scores = [r.sus_score for r in rows if r.sus_score is not None]

    per_question = []
    for q in QUESTIONS:
        values = [
            r.answers_json[str(q.id)]
            for r in rows
            if isinstance(r.answers_json, dict) and str(q.id) in r.answers_json
        ]
        per_question.append(
            {
                "id": q.id,
                "text": q.text,
                "kind": q.kind,
                "n": len(values),
                "mean": round(sum(values) / len(values), 2) if values else None,
                # The spread matters more than the mean at this sample size:
                # two clinicians at 1 and 5 average to the same 3 as two at 3.
                "distribution": {
                    str(v): values.count(v) for v in range(SCALE_MIN, SCALE_MAX + 1)
                },
            }
        )

    domain_means = [
        p["mean"] for p in per_question if p["id"] in DOMAIN_IDS and p["mean"] is not None
    ]

    return {
        "responses": len(rows),
        "sus": {
            "n": len(scores),
            "mean": round(sum(scores) / len(scores), 1) if scores else None,
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            # Published SUS benchmark, so a reader does not have to look it up.
            "benchmark_mean": 68.0,
        },
        "domain_mean": round(sum(domain_means) / len(domain_means), 2)
        if domain_means
        else None,
        "questions": per_question,
        "comments": [
            {"at": r.submitted_at.isoformat(), "role": r.role, "text": r.comment}
            for r in rows
            if r.comment
        ],
    }
