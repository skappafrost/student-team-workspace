"""Tests for the manage.py database admin CLI (T4-E1, spec B05).

Covers, each against an isolated ``tmp_path`` sqlite file:
- seed-demo creates the fixed demo dataset (2 users / 1 workspace /
  2 projects / 9 tasks) and is idempotent (second run only skips).
- seed-demo --fresh recreates the sqlite file, and REFUSES a Postgres
  URL (clean error, exit 2, no deletion attempt, no traceback) as well
  as in-memory sqlite.
- create-user creates a user; a duplicate email exits 1; an invalid
  (over-72-byte) password fails cleanly with exit 2 and no traceback.
- reset-password rotates credentials (new verifies, old stops working).
  NOTE: PR #76's reset-password takes only ``--email`` + new
  ``--password`` (there is no ``--old-password`` flag), so the
  "wrong credential" failure paths exercised here are: unknown user
  (exit 2, "no such user") and invalid new password (exit 2,
  "invalid password") — both clean, no traceback leak.
- db-status reports exactly 1 alembic head plus per-table row counts.

Isolation contract (T014 lesson): every test drives ``manage.main()``
in-process with an explicit ``--db-url`` pointing at ``tmp_path``.
``--db-url`` makes manage.py build a LOCAL engine, so the global
``database.engine`` is never rebound — this file MUST NOT call
``database.set_db_url``. Row assertions use a test-local engine built
via ``database._make_engine``.
"""

from __future__ import annotations

import gc

import database
import manage
import models
from app import verify_password
from database import Base
from sqlalchemy.orm import sessionmaker

SEED_EMAILS = ("demo-owner@example.com", "demo-member@example.com")
VALID_OLD_PASSWORD = "old-password-123"
VALID_NEW_PASSWORD = "new-password-456"
TOO_LONG_PASSWORD = "x" * 100  # > bcrypt 72-byte limit -> clean 422 inside manage


# ---------------------------------------------------------------------------
# Helpers (local engines only — never touch the global engine)
# ---------------------------------------------------------------------------

def _db_url(tmp_path, name: str = "manage.db") -> str:
    return "sqlite:///" + (tmp_path / name).as_posix()


def _counts(db_url: str) -> dict:
    eng = database._make_engine(db_url)
    try:
        db = sessionmaker(bind=eng)()
        try:
            return {
                "users": db.query(models.User).count(),
                "workspaces": db.query(models.Workspace).count(),
                "projects": db.query(models.Project).count(),
                "tasks": db.query(models.Task).count(),
            }
        finally:
            db.close()
    finally:
        eng.dispose()


def _get_user(db_url: str, email: str):
    eng = database._make_engine(db_url)
    try:
        db = sessionmaker(bind=eng)()
        try:
            user = db.query(models.User).filter_by(email=email).first()
            if user is not None:
                db.expunge(user)
            return user
        finally:
            db.close()
    finally:
        eng.dispose()


def _seed(db_url: str, *extra: str) -> int:
    return manage.main(["seed-demo", "--db-url", db_url, *extra])


def _ensure_schema(db_url: str) -> None:
    """Create tables on a local engine (mirrors ``alembic upgrade head``).

    manage.py assumes a migrated database: cmd_create_user queries the
    users table BEFORE its own create_all, so on a totally empty sqlite
    file it raises OperationalError instead of creating the user (found
    while testing; left untouched per this task's test-only scope —
    suggested follow-up: move create_all before the exists-check).
    """
    eng = database._make_engine(db_url)
    try:
        Base.metadata.create_all(bind=eng)
    finally:
        eng.dispose()


# ---------------------------------------------------------------------------
# seed-demo
# ---------------------------------------------------------------------------

def test_seed_demo_creates_expected_rows(tmp_path, capsys):
    url = _db_url(tmp_path)
    assert _seed(url) == 0
    out = capsys.readouterr().out
    assert "seed-demo done" in out
    assert _counts(url) == {"users": 2, "workspaces": 1, "projects": 2, "tasks": 9}
    eng = database._make_engine(url)
    try:
        db = sessionmaker(bind=eng)()
        try:
            ws = db.query(models.Workspace).filter_by(slug="demo").one()
            assert ws.name == "Demo Workspace"
            emails = sorted(u.email for u in db.query(models.User).all())
            assert emails == sorted(SEED_EMAILS)
        finally:
            db.close()
    finally:
        eng.dispose()


def test_seed_demo_idempotent(tmp_path, capsys):
    url = _db_url(tmp_path)
    assert _seed(url) == 0
    capsys.readouterr()
    assert _seed(url) == 0
    out = capsys.readouterr().out
    assert "exists, skipping" in out
    assert _counts(url) == {"users": 2, "workspaces": 1, "projects": 2, "tasks": 9}


def test_seed_demo_fresh_recreates_sqlite_file(tmp_path, capsys):
    url = _db_url(tmp_path)
    assert _seed(url) == 0
    capsys.readouterr()
    assert manage.main(
        ["create-user", "--email", "extra@example.com",
         "--password", VALID_NEW_PASSWORD, "--db-url", url]
    ) == 0
    capsys.readouterr()
    assert _counts(url)["users"] == 3
    # Windows holds sqlite files open while pooled connections from the
    # earlier IN-PROCESS manage calls are still alive (real CLI runs are
    # separate processes, so this never bites in production). Collect them
    # so --fresh can unlink the file.
    gc.collect()
    assert _seed(url, "--fresh") == 0
    out = capsys.readouterr().out
    assert "deleted" in out
    # The extra user died with the deleted file; the seed dataset is back.
    assert _counts(url) == {"users": 2, "workspaces": 1, "projects": 2, "tasks": 9}


def test_seed_fresh_refuses_postgres_url(tmp_path, capsys):
    # Canonical project driver (requirements.txt pins psycopg2-binary):
    # create_engine() imports the driver at build time, so the test must
    # use a scheme whose driver exists in every suite env (sqlite CI job
    # included) — "postgresql+psycopg" (v3) is NOT installed.
    pg_url = "postgresql+psycopg2://u:p@127.0.0.1:1/db"
    assert _seed(pg_url, "--fresh") == 2
    captured = capsys.readouterr()
    assert "refuses non-sqlite" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    # No deletion attempt and no file created: tmp dir stays empty.
    assert list(tmp_path.iterdir()) == []


def test_seed_fresh_refuses_memory_sqlite(tmp_path, capsys):
    assert _seed("sqlite:///:memory:", "--fresh") == 2
    captured = capsys.readouterr()
    assert "in-memory" in captured.err
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# create-user
# ---------------------------------------------------------------------------

def test_create_user_and_duplicate(tmp_path, capsys):
    url = _db_url(tmp_path)
    _ensure_schema(url)
    assert manage.main(
        ["create-user", "--email", "ana@example.com",
         "--password", VALID_NEW_PASSWORD, "--name", "Ana", "--db-url", url]
    ) == 0
    assert "created user ana@example.com" in capsys.readouterr().out
    user = _get_user(url, "ana@example.com")
    assert user is not None
    assert user.display_name == "Ana"
    assert verify_password(VALID_NEW_PASSWORD, user.hashed_password)

    assert manage.main(
        ["create-user", "--email", "ana@example.com",
         "--password", VALID_NEW_PASSWORD, "--db-url", url]
    ) == 1
    assert "already exists" in capsys.readouterr().out


def test_create_user_invalid_password_fails_cleanly(tmp_path, capsys):
    url = _db_url(tmp_path)
    _ensure_schema(url)
    assert manage.main(
        ["create-user", "--email", "bad@example.com",
         "--password", TOO_LONG_PASSWORD, "--db-url", url]
    ) == 2
    captured = capsys.readouterr()
    assert "invalid password" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out
    assert _get_user(url, "bad@example.com") is None


# ---------------------------------------------------------------------------
# reset-password
# ---------------------------------------------------------------------------

def test_reset_password_rotates_credentials(tmp_path, capsys):
    url = _db_url(tmp_path)
    _ensure_schema(url)
    assert manage.main(
        ["create-user", "--email", "rot@example.com",
         "--password", VALID_OLD_PASSWORD, "--db-url", url]
    ) == 0
    capsys.readouterr()
    assert manage.main(
        ["reset-password", "--email", "rot@example.com",
         "--password", VALID_NEW_PASSWORD, "--db-url", url]
    ) == 0
    assert "password reset for rot@example.com" in capsys.readouterr().out
    user = _get_user(url, "rot@example.com")
    assert verify_password(VALID_NEW_PASSWORD, user.hashed_password)
    # The old credential no longer works after rotation.
    assert not verify_password(VALID_OLD_PASSWORD, user.hashed_password)


def test_reset_password_unknown_user_fails_cleanly(tmp_path, capsys):
    url = _db_url(tmp_path)
    assert _seed(url) == 0
    capsys.readouterr()
    assert manage.main(
        ["reset-password", "--email", "ghost@example.com",
         "--password", VALID_NEW_PASSWORD, "--db-url", url]
    ) == 2
    captured = capsys.readouterr()
    assert "no such user" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_reset_password_invalid_new_password_fails_cleanly(tmp_path, capsys):
    url = _db_url(tmp_path)
    _ensure_schema(url)
    assert manage.main(
        ["create-user", "--email", "keep@example.com",
         "--password", VALID_OLD_PASSWORD, "--db-url", url]
    ) == 0
    capsys.readouterr()
    assert manage.main(
        ["reset-password", "--email", "keep@example.com",
         "--password", TOO_LONG_PASSWORD, "--db-url", url]
    ) == 2
    captured = capsys.readouterr()
    assert "invalid password" in captured.err
    assert "Traceback" not in captured.err
    # Failed reset leaves the stored hash untouched.
    user = _get_user(url, "keep@example.com")
    assert verify_password(VALID_OLD_PASSWORD, user.hashed_password)


# ---------------------------------------------------------------------------
# db-status
# ---------------------------------------------------------------------------

def test_db_status_reports_heads_and_counts(tmp_path, capsys):
    url = _db_url(tmp_path)
    assert _seed(url) == 0
    capsys.readouterr()
    assert manage.main(["db-status", "--db-url", url]) == 0
    out = capsys.readouterr().out
    assert "alembic heads (1):" in out
    assert "database: sqlite" in out
    assert "users: 2" in out
    assert "workspaces: 1" in out
    assert "projects: 2" in out
    assert "tasks: 9" in out
