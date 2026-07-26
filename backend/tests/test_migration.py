"""Tests for the additive schema migration in ``init_db``.

Regression: adding ``studies.analyzed_series_id`` shipped fine on a fresh
database (``create_all`` builds the table complete) but broke every deployed
one, because ``create_all`` never alters an existing table -- the running app
died with "Unknown column 'studies.analyzed_series_id'". Unit tests missed it
precisely because they always start from an empty database.
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.db import init_db


def _legacy_studies_table(engine) -> None:
    """Build a ``studies`` table as it looked before the series work."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE studies (
                    id VARCHAR(64) NOT NULL PRIMARY KEY,
                    patient_id INTEGER NOT NULL,
                    modality VARCHAR(32),
                    volume_path VARCHAR(1024),
                    display_path VARCHAR(1024),
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text("INSERT INTO studies (id, patient_id) VALUES ('old1', 1)")
        )


def test_init_db_adds_missing_column_to_existing_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    _legacy_studies_table(engine)
    assert "analyzed_series_id" not in {
        c["name"] for c in inspect(engine).get_columns("studies")
    }

    init_db(bind=engine)

    columns = {c["name"] for c in inspect(engine).get_columns("studies")}
    assert "analyzed_series_id" in columns, "migration must add the new column"
    # The pre-existing row survives untouched (additive, no rewrite).
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id FROM studies")).fetchall()
    assert [r[0] for r in row] == ["old1"]


def test_init_db_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    _legacy_studies_table(engine)

    init_db(bind=engine)
    init_db(bind=engine)  # must not raise "duplicate column"

    columns = {c["name"] for c in inspect(engine).get_columns("studies")}
    assert "analyzed_series_id" in columns


def test_init_db_creates_series_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/fresh.db")
    init_db(bind=engine)
    assert "series" in set(inspect(engine).get_table_names())


def _legacy_correction_log_table(engine) -> None:
    """Build ``correction_log`` as it looked before the submit queue."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE correction_log (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    study_id VARCHAR(64) NOT NULL,
                    field VARCHAR(128) NOT NULL,
                    old TEXT,
                    new TEXT,
                    at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO correction_log (study_id, field, old, new) "
                "VALUES ('old1', 'l4_l5.spinal_canal', 'Normal/Mild', 'Severe')"
            )
        )


def test_init_db_adds_submit_queue_columns_to_existing_correction_log(tmp_path):
    """Corrections already captured on a running install must survive.

    This table holds real doctor input, so the queue columns have to arrive by
    migration rather than by recreating the table.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    _legacy_correction_log_table(engine)

    init_db(bind=engine)

    columns = {c["name"] for c in inspect(engine).get_columns("correction_log")}
    assert {"submitted_at", "batch_id"} <= columns
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT study_id, new, submitted_at, batch_id FROM correction_log")
        ).fetchall()
    assert len(rows) == 1, "the existing correction must not be lost"
    assert rows[0][1] == "Severe", "and its content must be unchanged"
    assert rows[0][2] is None, "pre-existing corrections start out unsubmitted"
    assert rows[0][3] is None
