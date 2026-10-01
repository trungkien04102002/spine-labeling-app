from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import Settings

Base = declarative_base()

settings = Settings()

# create_engine() does not connect eagerly, so importing this module never
# requires a live MySQL server (needed for the SQLite-backed unit tests).
engine: Engine = create_engine(settings.mysql_dsn, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(bind: Engine = engine) -> None:
    """Create all tables on the given engine (defaults to the app's MySQL engine)."""
    # Import models so their tables register on Base.metadata before create_all.
    import app.models_db  # noqa: F401

    Base.metadata.create_all(bind=bind)
    _add_missing_columns(bind)


# Columns added to tables that already exist in deployed databases. create_all
# only ever creates missing *tables*, so a new column on an existing table is
# invisible to it and the app fails at query time. There is no Alembic setup
# here, so this runs the additive DDL itself: idempotent, additive only, and
# it never drops or rewrites anything.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column, type) -- nullable so existing rows need no backfill.
    ("studies", "analyzed_series_id", "INTEGER NULL"),
    ("correction_log", "submitted_at", "DATETIME NULL"),
    ("correction_log", "batch_id", "VARCHAR(64) NULL"),
    # The questionnaire dropped its SUS block, so the stored score is now the
    # mean of the clinical questions and the old column name lied.
    ("survey_response", "clinical_mean", "FLOAT NULL"),
    # Rooms (2026-09-28): who each row belongs to.
    ("patients", "reader_id", "INTEGER NULL"),
    ("studies", "reader_id", "INTEGER NULL"),
    ("correction_log", "reader_id", "INTEGER NULL"),
    ("survey_response", "reader_id", "INTEGER NULL"),
    ("readers", "code", "VARCHAR(16) NULL"),
    # Room PINs (2026-10-01): pick your name, then type your PIN.
    ("readers", "pin_hash", "VARCHAR(128) NULL"),
]


def _add_missing_columns(bind: Engine) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table, column, ddl_type in _ADDED_COLUMNS:
        if table not in existing_tables:
            continue  # create_all just made it, with the column already there
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column in columns:
            continue
        with bind.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
