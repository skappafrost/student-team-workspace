"""SQLAlchemy database setup for STW backend."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

import logging_mw
from config import settings

DATABASE_URL = settings.database_url


def _make_engine(url: str):
    """Create a SQLAlchemy engine with STW-wide settings.

    For SQLite, foreign-key enforcement is switched ON for every connection
    (T014). SQLite ships with ``PRAGMA foreign_keys`` off by default, which
    silently ignores the ``ondelete`` rules declared on the models; without
    this, raw/bulk deletes leave orphans on dev/test while prod (Postgres)
    enforces them.
    """
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    # TA6-1: every engine the app builds (including test rebinds via
    # set_db_url) gets slow-query logging; see logging_mw for the events.
    logging_mw.attach_slow_query_logging(engine)
    return engine


engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_db_url(url: str) -> None:
    """Reconfigure the module-level engine and sessionmaker for tests."""
    global engine, SessionLocal
    engine = _make_engine(url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
