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
- migrate_to_head applies the chain in-process: fresh database, already-at-head
  database (no-op), an unstamped create_all database (fails loudly), and it leaves
  the process's log capture working.
- stamp with no --db-url, driven the way a developer drives it (a real process,
  no DATABASE_URL, only a .env file): alembic's env.py fallback resolves the same
  database the application's engine opens.

Isolation contract (T014 lesson): every test drives ``manage.main()``
in-process with an explicit ``--db-url`` pointing at ``tmp_path``.
``--db-url`` makes manage.py build a LOCAL engine, so the global
``database.engine`` is never rebound — this file MUST NOT call
``database.set_db_url``. Row assertions use a test-local engine built
via ``database._make_engine``. The single exception drives ``manage.py`` as a
subprocess: the no-``--db-url`` path it pins resolves the database at module
import time, and in-process tests are forbidden to rebind that global.
"""

from __future__ import annotations

import gc
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

import database
import manage
import models
from app import verify_password
from database import Base

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


# ---------------------------------------------------------------------------
# stamp: the repair for a database built by create_all
# ---------------------------------------------------------------------------


def _create_all_url(tmp_path, name="stamped.db") -> str:
    from sqlalchemy import create_engine

    path = tmp_path / name
    url = f"sqlite:///{path.as_posix()}"
    Base.metadata.create_all(create_engine(url))
    return url


def _applied(url: str) -> list[str]:
    from sqlalchemy import create_engine, text

    with create_engine(url).connect() as conn:
        try:
            return sorted(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
        except Exception:
            return []


def test_stamp_repairs_a_create_all_database(tmp_path):
    """The full story in one test: upgrade dies, stamp records, upgrade is a no-op.

    `Base.metadata.create_all` is what `conftest.py` runs per test, and was what
    `app.py` ran at startup, so "every table, no alembic_version" is the state
    most existing databases on this project are in. `alembic upgrade head` reads
    that as "start from base" and dies on the first unconditional `create_table`,
    which looks like a broken migration and is not one.
    """
    from alembic import command
    from conftest import run_alembic

    url = _create_all_url(tmp_path)

    with pytest.raises(Exception, match="already exists"):
        with manage._alembic_target(url):
            run_alembic(command.upgrade, manage._alembic_config(url), "head")

    assert manage.main(["stamp", "--db-url", url]) == 0
    assert _applied(url) == manage._alembic_heads()

    with manage._alembic_target(url):
        run_alembic(command.upgrade, manage._alembic_config(url), "head")


def test_stamp_leaves_log_capture_working(tmp_path, caplog):
    """`stamp` must not hand back an app whose loggers were disabled.

    This one is measured, not theorised: the first version of `cmd_stamp` called
    `command.stamp` bare, `alembic/env.py` ran `fileConfig()` (which defaults to
    `disable_existing_loggers=True`), and the next `caplog` assertion in the
    session — `test_ws.py::test_broadcast_bounds_one_stalled_peer` — reported
    `records=[]` for a line that had demonstrably been logged. CI red, everything
    green locally.
    """
    import logging

    url = _create_all_url(tmp_path, "logging.db")
    assert manage.main(["stamp", "--db-url", url]) == 0

    with caplog.at_level(logging.WARNING, logger="stw"):
        logging.getLogger("stw").warning("after stamp")
    assert "after stamp" in caplog.text, (
        "the stw logger was left disabled by the alembic call: nothing downstream "
        "will be captured, and a test asserting on it passes on empty input"
    )


def test_stamp_targets_db_url_not_the_ambient_database_url(tmp_path, monkeypatch):
    """`--db-url` must name the database that actually gets stamped.

    `alembic/env.py:get_database_url()` reads `DATABASE_URL` before `alembic.ini`,
    so stamping without overriding it reports success while writing
    `alembic_version` into whatever the process environment points at — which for
    a container, and for every test session, is a different database than the one
    the operator named.
    """
    ambient = _create_all_url(tmp_path, "ambient.db")
    target = _create_all_url(tmp_path, "target.db")
    monkeypatch.setenv("DATABASE_URL", ambient)
    assert _applied(ambient) == [] and _applied(target) == []

    assert manage.main(["stamp", "--db-url", target]) == 0

    assert _applied(target) == manage._alembic_heads()
    assert _applied(ambient) == [], "stamp wrote the ambient database, not --db-url"



def test_stamp_refuses_a_database_with_no_tables(tmp_path, capsys):
    """Stamping is a statement of fact, so it must fail when the fact is false.

    Silently stamping an empty database would leave `alembic upgrade head` a no-op
    over a schema that was never built — a quieter and worse failure than the one
    this command exists to repair.
    """
    import sqlite3

    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()

    rc = manage.main(["stamp", "--db-url", f"sqlite:///{path.as_posix()}"])
    assert rc == 2
    assert "upgrade head" in capsys.readouterr().err


def test_db_status_names_the_missing_stamp(tmp_path, capsys):
    """`db-status` is where a confused developer looks; it has to say what to do."""
    url = _create_all_url(tmp_path, "status.db")

    assert manage.main(["db-status", "--db-url", url]) == 0
    out = capsys.readouterr().out
    assert "alembic version (applied): (none)" in out
    assert "create_all" in out
    assert "manage.py stamp" in out


def test_db_status_lists_applied_revisions_after_a_stamp(tmp_path, capsys):
    url = _create_all_url(tmp_path, "stamped2.db")
    assert manage.main(["stamp", "--db-url", url]) == 0

    assert manage.main(["db-status", "--db-url", url]) == 0
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("alembic version (applied):")
    ]
    assert len(lines) == 1, lines
    assert lines[0] != "alembic version (applied): (none)", lines[0]
    assert "manage.py stamp" not in lines[0]


# ---------------------------------------------------------------------------
# migrate_to_head: the in-process chain an entrypoint runs before it serves
# ---------------------------------------------------------------------------


def test_migrate_to_head_builds_the_schema_on_a_fresh_database(tmp_path):
    """An empty file comes back with every table and the head recorded.

    This is the path `smoke_server.py` takes: without it the server binds, `/health`
    answers 200, and every route that reads a table 500s — a smoke test that passes
    on a database with no schema at all.
    """
    url = _db_url(tmp_path, "migrate.db")

    assert manage.migrate_to_head(url) == manage._alembic_heads()
    assert _counts(url) == {
        "users": 0,
        "workspaces": 0,
        "projects": 0,
        "tasks": 0,
    }


def test_migrate_to_head_is_a_no_op_once_the_database_is_at_head(tmp_path):
    """Running the chain twice is safe, which is what makes a migrate step cheap.

    CI migrates `ci_e2e.db` in its own step and the Playwright backend
    `webServer` command runs the same chain again before uvicorn starts; the
    second run must not fail.
    """
    url = _db_url(tmp_path, "migrate_twice.db")
    first = manage.migrate_to_head(url)

    assert manage.migrate_to_head(url) == first


def test_migrate_to_head_stops_at_an_unstamped_create_all_database(tmp_path):
    """The loud half of the contract: a repaired database is required first.

    Failing here instead of quietly falling back to `create_all` is the point —
    `stamp` is the documented repair, and an entrypoint that swallowed this error
    would be the old bug wearing a new coat.
    """
    url = _create_all_url(tmp_path, "unstamped_migrate.db")

    with pytest.raises(Exception, match="already exists"):
        manage.migrate_to_head(url)


def test_migrate_to_head_leaves_log_capture_working(tmp_path, caplog):
    """Same trap `stamp` hit: `env.py`'s `fileConfig()` disables `stw.*` loggers.

    A smoke run that mutes the app's logging is a smoke run whose warnings vanish,
    so the guard is tested for the upgrade path too, not only for `stamp`.
    """
    import logging

    url = _db_url(tmp_path, "migrate_logging.db")
    manage.migrate_to_head(url)

    with caplog.at_level(logging.WARNING, logger="stw"):
        logging.getLogger("stw").warning("after migrate")
    assert "after migrate" in caplog.text, (
        "the alembic call left the stw logger disabled"
    )


# ---------------------------------------------------------------------------
# stamp without --db-url: alembic and the app must resolve the SAME database
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parent


def _quickstart_env() -> dict[str, str]:
    """The environment of a developer who only ever copied `.env.example`.

    No `DATABASE_URL` in the process environment — the `.env` file in `cwd` is
    the only configuration either side of the split brain can see. `PYTHONPATH`
    lets `python -c` import the backend packages while the cwd stays `tmp_path`,
    which is where `Settings` reads `.env` from.
    """
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(BACKEND_DIR)
    return env


def _create_all_via_app_resolution(tmp_path) -> None:
    """Materialise the app's tables in the database the app's own resolution opens.

    Not in-process on purpose: the global ``database.engine`` was bound from the
    test session's environment at import time, and the resolution under test is
    the one that happens at import.
    """
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import database, models; "
            "database.Base.metadata.create_all(bind=database.engine)",
        ],
        cwd=tmp_path,
        env=_quickstart_env(),
        check=True,
        timeout=180,
    )


def test_stamp_without_db_url_targets_the_database_the_app_opens(tmp_path):
    """The split brain this PR exists to kill, pinned end to end.

    `stamp` without `--db-url` inspects `database.engine` — the URL `Settings`
    resolved from `.env` at import — but records `alembic_version` through an
    in-process alembic run whose `env.py` resolves the URL separately. Before
    the fallback became a fresh `Settings()`, that second resolution ignored
    `.env` with `DATABASE_URL` unset: it verified tables in the `.env` database,
    stamped the hard-coded Postgres fallback instead, printed
    `alembic_version: (none)` and still exited 0. Against the new `env.py` both
    resolutions name the same file, the stamp lands where the app will look,
    and the report says so.
    """
    (tmp_path / ".env").write_text(
        "DATABASE_URL=sqlite:///./stamp_app.db\n", encoding="utf-8"
    )
    _create_all_via_app_resolution(tmp_path)
    url = _db_url(tmp_path, "stamp_app.db")
    assert _applied(url) == [], "the create_all step also stamped; nothing to repair"

    proc = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "manage.py"), "stamp"],
        cwd=tmp_path,
        env=_quickstart_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert "(none)" not in proc.stdout, proc.stdout
    assert _applied(url) == manage._alembic_heads(), (
        "stamp recorded a revision somewhere other than the database the app opens"
    )
