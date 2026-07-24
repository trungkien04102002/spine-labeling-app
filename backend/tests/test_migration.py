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
