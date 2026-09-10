"""T014 - SQLite foreign-key enforcement on app engines.

SQLite ignores declared ``ondelete`` rules unless ``PRAGMA foreign_keys=ON``
is set per connection.  Engines built through ``database._make_engine`` (the
module-level engine and every ``set_db_url`` reconfiguration) must turn it on,
so raw/bulk deletes and inserts are integrity-checked exactly like prod
(Postgres).  These tests exercise the raw SQL path - no ORM cascade involved.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

import database
from database import Base
import models  # noqa: F401  - registers all models on Base.metadata


@pytest.fixture(scope="function")
def fk_engine(tmp_path):
    url = "sqlite:///" + (tmp_path / "fk.db").as_posix()
    engine = database._make_engine(url)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _fk_pragma(engine):
    with engine.connect() as conn:
        return conn.execute(text("PRAGMA foreign_keys")).scalar()


def test_make_engine_enables_fk_pragma(fk_engine):
    assert _fk_pragma(fk_engine) == 1


def test_module_engine_enables_fk_pragma():
    # The engine created at import time must carry the pragma too.
    assert _fk_pragma(database.engine) == 1


def test_set_db_url_keeps_fk_pragma(tmp_path):
    url = "sqlite:///" + (tmp_path / "fk_set_db_url.db").as_posix()
    database.set_db_url(url)
    try:
        assert _fk_pragma(database.engine) == 1
    finally:
        # Restore the suite's shared test DB (same URL conftest pins via
        # DATABASE_URL). Restoring any other file strands later tests on a
        # DB without tables (cross-test pollution).
        from conftest import TEST_DB_PATH
        database.set_db_url(f"sqlite:///{TEST_DB_PATH}")


def test_raw_insert_with_bogus_fk_raises_integrity_error(fk_engine):
    with fk_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO workspace_members (id, workspace_id, user_id, role) "
                    "VALUES ('m1', 'no-such-workspace', 'no-such-user', 'owner')"
                )
            )
            conn.commit()


def test_raw_delete_cascades_at_db_level(fk_engine):
    """Deleting a parent with raw SQL must cascade to children (no ORM)."""
    with fk_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, display_name, is_active) VALUES ('u1', 'a@b.c', 'A', 1)"))
        conn.execute(
            text(
                "INSERT INTO workspaces (id, name, slug) "
                "VALUES ('w1', 'WS', 'ws')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO workspace_members (id, workspace_id, user_id, role) "
                "VALUES ('m1', 'w1', 'u1', 'owner')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, workspace_id, name, status) "
                "VALUES ('p1', 'w1', 'P', 'active')"
            )
        )

    with fk_engine.begin() as conn:
        conn.execute(text("DELETE FROM workspaces WHERE id = 'w1'"))

    with fk_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM workspace_members")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM projects")).scalar() == 0
