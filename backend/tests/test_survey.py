"""Tests for the clinician questionnaire."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.survey_questions import DOMAIN_IDS, QUESTIONS, SUS_IDS, sus_score


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


def _ideal() -> dict[int, int]:
    """Agree with every positive item, disagree with every negative one."""
    return {
        q.id: (1 if q.kind == "sus_negative" else 5)
        for q in QUESTIONS
    }


def test_questions_are_served_with_their_scale(client):
    body = client.get("/survey/questions").json()
    assert len(body["questions"]) == 17
    assert len(body["scale"]["labels"]) == 5
    # Served, not duplicated in the frontend, so the text can only live here.
    assert body["questions"][0]["text"].startswith("Tôi nghĩ")


def test_sus_spans_0_to_100_and_catches_a_straight_column():
    """Answering 5 to everything must NOT score full marks.

    That is the reason SUS alternates positive and negative wording, and the
    reason it is worth using over fifteen questions of our own: someone
    ticking one column all the way down lands at 50, not 100.
    """
    assert sus_score({q.id: (1 if q.kind == "sus_negative" else 5) for q in QUESTIONS if q.kind != "domain"}) == 100.0
    assert sus_score({q.id: (5 if q.kind == "sus_negative" else 1) for q in QUESTIONS if q.kind != "domain"}) == 0.0
    assert sus_score({qid: 5 for qid in SUS_IDS}) == 50.0
    assert sus_score({qid: 3 for qid in SUS_IDS}) == 50.0


def test_submit_scores_and_stores(client):
    resp = client.post(
        "/survey/responses",
        json={"answers": _ideal(), "role": "Bác sĩ chẩn đoán hình ảnh", "comment": "Dễ dùng."},
    )
    assert resp.status_code == 201
    assert resp.json()["sus_score"] == 100.0

    summary = client.get("/survey/summary").json()
    assert summary["responses"] == 1
    assert summary["sus"]["mean"] == 100.0
    assert summary["sus"]["benchmark_mean"] == 68.0
    assert summary["comments"][0]["text"] == "Dễ dùng."


def test_the_ten_usability_items_are_required(client):
    """A partial SUS scores lower for a reason unrelated to the tool."""
    answers = _ideal()
    del answers[SUS_IDS[0]]
    resp = client.post("/survey/responses", json={"answers": answers})
    assert resp.status_code == 400
    assert str(SUS_IDS[0]) in resp.json()["detail"]


def test_the_five_tool_questions_may_be_skipped(client):
    """Someone who never edited a mask should skip that item, not guess."""
    answers = {qid: v for qid, v in _ideal().items() if qid not in DOMAIN_IDS}
    assert client.post("/survey/responses", json={"answers": answers}).status_code == 201


def test_out_of_range_and_unknown_answers_are_refused(client):
    bad = _ideal() | {SUS_IDS[0]: 7}
    assert client.post("/survey/responses", json={"answers": bad}).status_code == 400
    unknown = _ideal() | {999: 3}
    assert client.post("/survey/responses", json={"answers": unknown}).status_code == 400


def test_summary_reports_spread_not_just_the_mean(client):
    """Two clinicians at 1 and 5 average to the same 3 as two at 3.

    At this sample size the mean alone is misleading, so the distribution and
    the count behind each question have to be reported with it.
    """
    for value in (1, 5):
        answers = _ideal() | {DOMAIN_IDS[0]: value}
        client.post("/survey/responses", json={"answers": answers})

    q = next(
        item
        for item in client.get("/survey/summary").json()["questions"]
        if item["id"] == DOMAIN_IDS[0]
    )
    assert q["mean"] == 3.0
    assert q["n"] == 2
    assert q["distribution"]["1"] == 1 and q["distribution"]["5"] == 1
