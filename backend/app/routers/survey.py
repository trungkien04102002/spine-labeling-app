"""Clinician questionnaire: serve the questions, take answers, report them.

The questions are served rather than duplicated in the frontend, so there is
one place to edit them and no way for the two halves to drift apart while
answers are being collected.
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
    COMPARE_TITLE_A_ONLY,
    MODEL_B_PAIRS,
    QUESTIONS,
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
    """The questionnaire, in presentation order, with its rating scale.

    The model-B items appear only while clinicians can see model B: asking
    about a panel they were never shown would collect guesses.
    """
    show_b = is_visible(settings)
    shown = [q for q in QUESTIONS if show_b or q.kind != "reference_b"]
    return {
        "questions": [q.as_dict() for q in shown],
        "groups": [g for g in GROUPS if any(q.group == g for q in shown)],
        "sections": [
            {
                "title": title if show_b or not title.startswith("Phần 2") else COMPARE_TITLE_A_ONLY,
                "groups": [g for g in groups if any(q.group == g for q in shown)],
            }
            for title, groups in SECTIONS
            if any(q.group in groups for q in shown)
        ],
        # Criteria asked of both models: render A and B together.
        "pairs": [
            {"title": title, "a": a, "b": b if show_b else None}
            for title, a, b in COMPARE_PAIRS
        ],
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
        reader_id=reader.id if reader is not None else None,
        # The room's name stands in when the form's name field is left blank,
        # so a response is attributable without asking twice.
        respondent=(payload.respondent or (reader.name if reader else None)),
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


@router.get("/survey/summary", dependencies=[Depends(require_admin)])
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
        # Same question, both models: which one clinicians rated lower.
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
    """Every response on its own, newest first.

    The summary averages clinicians together, which is what a report quotes
    but not what a reader needs when one answer looks odd: which clinician said
    it, what else they said, and whether their comment explains it.
    """
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
    """One row per response, one column per question, for Excel or SPSS.

    Column headers carry the question number AND its text, so the file still
    means something once it is separated from this code -- in an appendix, or
    six months later.
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


# Excel reads a CSV as the local ANSI code page unless it starts with a UTF-8
# byte-order mark, which turns every Vietnamese answer and comment into
# mojibake. The mark costs three bytes and is ignored by everything else.
_UTF8_BOM = "\ufeff"


@router.get("/survey/responses.csv", dependencies=[Depends(require_admin)])
def responses_csv(db: Session = Depends(get_db)) -> Response:
    return Response(
        content=_UTF8_BOM + survey_csv(db),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="survey_responses.csv"'},
    )


@router.delete("/survey/responses/{response_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_response(response_id: int, db: Session = Depends(get_db)) -> Response:
    """Remove one response -- for a test submission, not for tidying results.

    A trial run by one person produces its own practice answers, and those must
    not be averaged in with the clinicians'. The operator page asks before
    calling this, and says the deletion is permanent.
    """
    row = db.get(SurveyResponse, response_id)
    if row is None:
        raise HTTPException(404, f"No response {response_id}")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
