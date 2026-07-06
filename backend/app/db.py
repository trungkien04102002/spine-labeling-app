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
    Base.metadata.create_all(bind=bind)
