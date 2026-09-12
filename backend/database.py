"""SQLAlchemy database setup for STW backend."""

import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

DATABASE_URL = settings.database_url

# SQLite-specific args for thread safety.
engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs = {"connect_args": {"check_same_thread": False}}

engine = create_engine(DATABASE_URL, **engine_kwargs)
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
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = sqlalchemy.create_engine(url, **kwargs)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
