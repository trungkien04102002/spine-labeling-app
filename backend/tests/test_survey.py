"""Tests for the clinician questionnaire."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.survey_questions import (
    CLINICAL_IDS,
    QUESTIONS,
    REQUIRED_IDS,
    USABILITY_IDS,
)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _only_required(value: int = 4) -> dict[int, int]:
    return {qid: value for qid in REQUIRED_IDS}


def test_the_questionnaire_is_mostly_about_the_model(client):
    """The balance is the point: fourteen clinical questions against two.

    An earlier draft spent ten of nineteen on usability to buy a comparable
    score. This asserts the trade that replaced it, so a later edit cannot
    quietly drift back.
    """
    body = client.get("/survey/questions").json()
    assert len(body["questions"]) == 19
    assert len(CLINICAL_IDS) == 17 and len(USABILITY_IDS) == 2
    assert body["groups"][0] == "Phân vùng"


def test_only_the_six_answerable_by_anyone_are_required(client):
    """Thirteen questions may be skipped, and skipping has to actually work."""
    resp = client.post("/survey/responses", json={"answers": _only_required()})
    assert resp.status_code == 201
    assert resp.json()["clinical_mean"] == 4.0


def test_a_missing_required_answer_is_refused_by_number(client):
    answers = _only_required()
    del answers[REQUIRED_IDS[0]]
    resp = client.post("/survey/responses", json={"answers": answers})
    assert resp.status_code == 400
    assert str(REQUIRED_IDS[0]) in resp.json()["detail"]


def test_skipping_never_drags_a_score_down(client):
    """A blank is not a zero.

    A clinician who never looked at foraminal crops must not push the model's
    number down by leaving that question alone -- otherwise the honest answer
    is punished and everyone guesses instead.
    """
    full = client.post(
        "/survey/responses", json={"answers": {q.id: 4 for q in QUESTIONS}}
    ).json()
    partial = client.post(
        "/survey/responses", json={"answers": _only_required(4)}
    ).json()
    assert full["clinical_mean"] == partial["clinical_mean"] == 4.0


def test_out_of_range_and_unknown_answers_are_refused(client):
    assert (
        client.post(
            "/survey/responses", json={"answers": _only_required() | {REQUIRED_IDS[0]: 9}}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/survey/responses", json={"answers": _only_required() | {999: 3}}
        ).status_code
        == 400
    )


def test_summary_separates_the_two_blocks_and_the_groups(client):
    client.post(
        "/survey/responses",
        json={
            "answers": {q.id: (2 if q.kind == "usability" else 5) for q in QUESTIONS},
            "comment": "Chẩn đoán tốt, giao diện khó.",
        },
    )
    body = client.get("/survey/summary").json()
    assert body["clinical"]["mean"] == 5.0
    assert body["usability"]["mean"] == 2.0
    assert {g["name"] for g in body["groups"]} >= {"Điểm chẩn đoán", "Khi AI sai"}
    assert body["comments"][0]["text"].startswith("Chẩn đoán")


def test_summary_reports_spread_and_per_question_counts(client):
    """Two clinicians at 1 and 5 average to the same 3 as two at 3."""
    target = CLINICAL_IDS[0]
    for value in (1, 5):
        client.post(
            "/survey/responses", json={"answers": _only_required() | {target: value}}
        )

    q = next(
        item
        for item in client.get("/survey/summary").json()["questions"]
        if item["id"] == target
    )
    assert q["mean"] == 3.0 and q["n"] == 2
    assert q["distribution"]["1"] == 1 and q["distribution"]["5"] == 1
