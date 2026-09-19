"""Ops hardening tests: retention policy, safe purge, integrity check (TA5-3).

Contract covered (never destructive by default):
- dry-run changes nothing; purge requires --apply / apply=True
- purge removes only orphans (old rowless bytes + rows with missing bytes)
- integrity check detects row/disk mismatch and mutates nothing
- retention is opt-in (RETENTION_ENABLED) and separate from orphan age
- counts are reported before any deletion (count-first contract)
"""

from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

import pytest
from fastapi.staticfiles import StaticFiles

import app as app_module
import database
import maintenance
import manage
import models
import retention
from conftest import make_user
from database import Base

# ---------------------------------------------------------------------------
# Fixtures (mirror test_maintenance.py's isolation contract: local engines only)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_url(tmp_path):
    # Same file the CLI tests pass as --db-url (local engine, never global).
    return "sqlite:///" + str(tmp_path / "test.db")


@pytest.fixture()
def db_session(db_url):
    from sqlalchemy.orm import sessionmaker

    eng = database._make_engine(db_url)
    Base.metadata.create_all(bind=eng)
    db = sessionmaker(bind=eng)()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=eng)


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", d)
    app_module.app.router.routes[:] = [
        r for r in app_module.app.router.routes if getattr(r, "name", None) != "uploads"
    ]
    app_module.app.mount("/uploads", StaticFiles(directory=str(d)), name="uploads")
    return d


@pytest.fixture()
def armed(monkeypatch):
    """Arm retention for the duration of one test (never global state)."""
    monkeypatch.setattr(retention.settings, "retention_enabled", True)


@pytest.fixture()
def retention_days(monkeypatch):
    def _apply(days):
        monkeypatch.setattr(retention.settings, "upload_retention_days", days)

    return _apply


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_workspace(db, workspace_id: str = "ws-1"):
    ws = db.get(models.Workspace, workspace_id)
    if ws is None:
        ws = models.Workspace(id=workspace_id, name="WS", slug=workspace_id)
        db.add(ws)
        db.commit()
    return ws


def add_file_row(db, file_id: str, storage_key: str, age_days: float | None = None):
    """Create a File row (+ workspace/user for FK enforcement)."""
    ensure_workspace(db)
    make_user(db, "user-1")
    created = None
    if age_days is not None:
        created = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age_days)
        created = created.replace(tzinfo=None)  # stored naive on SQLite
    db.add(
        models.File(
            id=file_id,
            workspace_id="ws-1",
            uploader_id="user-1",
            original_name=storage_key,
            storage_key=storage_key,
            mime_type="application/pdf",
            size_bytes=1,
            created_at=created,
        )
    )
    db.commit()


def age_file(path: Path, hours: float):
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


def _db_url(tmp_path, name: str = "test.db") -> str:
    # Same file the CLI tests pass as --db-url (local engine, never global).
    return "sqlite:///" + str(tmp_path / name)


# ---------------------------------------------------------------------------
# Retention policy helpers (retention.py)
# ---------------------------------------------------------------------------

def test_retention_defaults_are_safe():
    # Never armed by default; no age-based deletion.
    assert retention.retention_enabled() is False
    assert retention.retention_cutoff() is None


def test_retention_cutoff_when_configured(retention_days):
    retention_days(90)
    assert retention.retention_cutoff() == dt.timedelta(days=90)


def test_retention_disabled_days_zero(retention_days):
    # Explicit 0 = "keep everything" (no age-based deletion).
    retention_days(0)
    assert retention.retention_cutoff() is None


def test_orphan_min_age_default_is_24h():
    assert retention.orphan_min_age() == dt.timedelta(hours=24)


# ---------------------------------------------------------------------------
# DRY-RUN: never deletes anything
# ---------------------------------------------------------------------------

def test_dry_run_changes_nothing(db_session, upload_dir):
    add_file_row(db_session, "f-missing", "gone.pdf")
    add_file_row(db_session, "f-old", "old.pdf", age_days=400)
    (upload_dir / "old.pdf").write_bytes(b"x")
    old_orphan = upload_dir / "old-orphan.bin"
    old_orphan.write_bytes(b"x")
    age_file(old_orphan, hours=25)

    report = maintenance.purge_orphans(
        db_session, upload_dir, apply=False, retention_cutoff=dt.timedelta(days=30)
    )

    assert report["apply"] is False
    assert report["retention_rows"] == []
    assert report["retention_files"] == []
    assert report["retention_skipped"] == ["f-old"]
    assert report["dropped_rows"] == []
    assert report["unlinked_files"] == []
    # Nothing on disk or in the DB changed.
    assert db_session.get(models.File, "f-missing") is not None
    assert db_session.get(models.File, "f-old") is not None
    assert old_orphan.exists()
    assert (upload_dir / "old.pdf").exists()


def test_dry_run_reports_counts_first(db_session, upload_dir, caplog):
    """The count-first contract: counts are computed before any deletion."""
    add_file_row(db_session, "f-missing", "gone.pdf")
    add_file_row(db_session, "f-old", "old.pdf", age_days=400)
    (upload_dir / "old.pdf").write_bytes(b"x")
    old_orphan = upload_dir / "old-orphan.bin"
    old_orphan.write_bytes(b"x")
    age_file(old_orphan, hours=25)

    # The report (and its counts) is fully populated before any deletion.
    report = maintenance.purge_orphans(
        db_session, upload_dir, apply=False, retention_cutoff=dt.timedelta(days=30)
    )
    counts = maintenance._summary(report)

    assert counts["missing_bytes_rows"] == 1
    assert counts["orphan_files"] == 1
    # Retention is opt-in: the old row is REPORTED but not deleted.
    assert counts["retention_rows"] == 0
    assert counts["retention_skipped"] == 1
    # Nothing was deleted.
    assert counts["dropped_rows"] == 0
    assert counts["unlinked_files"] == 0
    assert db_session.get(models.File, "f-missing") is not None
    assert old_orphan.exists()


# ---------------------------------------------------------------------------
# PURGE: removes only orphans
# ---------------------------------------------------------------------------

def test_purge_apply_removes_only_orphans(db_session, upload_dir, armed):
    add_file_row(db_session, "f-missing", "gone.pdf")  # bytes gone -> row dropped
    add_file_row(db_session, "f-old", "old.pdf", age_days=400)  # retention purge
    add_file_row(db_session, "f-fresh", "fresh.pdf")  # recent + bytes present -> kept
    (upload_dir / "old.pdf").write_bytes(b"x")
    (upload_dir / "fresh.pdf").write_bytes(b"x")
    old_orphan = upload_dir / "old-orphan.bin"
    old_orphan.write_bytes(b"x")
    age_file(old_orphan, hours=25)
    fresh_orphan = upload_dir / "fresh-orphan.bin"
    fresh_orphan.write_bytes(b"x")

    report = maintenance.purge_orphans(
        db_session, upload_dir, apply=True, retention_cutoff=dt.timedelta(days=30)
    )

    # Only the real orphans were removed; the fresh pair survives.
    assert report["dropped_rows"] == ["gone.pdf", "old.pdf"]
    assert sorted(report["unlinked_files"]) == ["old-orphan.bin", "old.pdf"]
    assert db_session.get(models.File, "f-missing") is None
    assert db_session.get(models.File, "f-old") is None
    assert db_session.get(models.File, "f-fresh") is not None
    assert not (upload_dir / "old.pdf").exists()
    assert (upload_dir / "fresh.pdf").exists()
    assert not old_orphan.exists()
    assert fresh_orphan.exists()


def test_purge_retention_not_armed_keeps_old_rows(db_session, upload_dir):
    """Retention is opt-in: old rows survive purge when RETENTION_ENABLED is off."""
    add_file_row(db_session, "f-old", "old.pdf", age_days=400)
    (upload_dir / "old.pdf").write_bytes(b"x")

    report = maintenance.purge_orphans(
        db_session, upload_dir, apply=True, retention_cutoff=dt.timedelta(days=30)
    )

    assert report["retention_rows"] == []
    assert report["retention_files"] == []
    assert db_session.get(models.File, "f-old") is not None
    assert (upload_dir / "old.pdf").exists()


def test_purge_without_retention_cutoff_is_a_noop_for_old_rows(db_session, upload_dir):
    """No retention window passed -> old File rows are never touched."""
    add_file_row(db_session, "f-old", "old.pdf", age_days=400)
    (upload_dir / "old.pdf").write_bytes(b"x")

    report = maintenance.purge_orphans(db_session, upload_dir, apply=True)

    assert report["retention_rows"] == []
    assert report["retention_files"] == []
    assert report["retention_skipped"] == []
    assert db_session.get(models.File, "f-old") is not None
    assert (upload_dir / "old.pdf").exists()


def test_purge_orphan_age_governs_rowless_bytes_only(db_session, upload_dir):
    """min_age applies to rowless bytes only, never to File rows."""
    add_file_row(db_session, "f-old", "old.pdf", age_days=400)
    (upload_dir / "old.pdf").write_bytes(b"x")

    report = maintenance.purge_orphans(db_session, upload_dir, apply=True)

    assert report["retention_rows"] == []
    assert db_session.get(models.File, "f-old") is not None
    assert (upload_dir / "old.pdf").exists()


# ---------------------------------------------------------------------------
# INTEGRITY CHECK: detects mismatch, never mutates
# ---------------------------------------------------------------------------

def test_integrity_check_detects_mismatch(db_session, upload_dir):
    add_file_row(db_session, "f-missing", "gone.pdf")  # row, no bytes
    old_orphan = upload_dir / "old-orphan.bin"          # bytes, no row
    old_orphan.write_bytes(b"x")
    age_file(old_orphan, hours=25)

    report = maintenance.integrity_check(db_session, upload_dir)

    assert report["apply"] is False
    assert ("f-missing", "gone.pdf") in report["missing_bytes_rows"]
    assert report["orphan_files"] == ["old-orphan.bin"]
    assert report["skipped_fresh_files"] == []
    # Read-only: nothing changed.
    assert db_session.get(models.File, "f-missing") is not None
    assert old_orphan.exists()


def test_integrity_check_detects_fresh_orphans(db_session, upload_dir):
    add_file_row(db_session, "f-present", "kept.pdf")
    (upload_dir / "kept.pdf").write_bytes(b"x")
    fresh = upload_dir / "inflight.bin"
    fresh.write_bytes(b"x")

    report = maintenance.integrity_check(db_session, upload_dir)

    assert report["orphan_files"] == []
    assert "inflight.bin" in report["skipped_fresh_files"]
    assert fresh.exists()
    assert (upload_dir / "kept.pdf").exists()


def test_integrity_check_is_pure_read(db_session, upload_dir, monkeypatch):
    """integrity_check must never reach a deletion path."""
    add_file_row(db_session, "f-missing", "gone.pdf")

    def _no_delete(*args, **kwargs):
        raise AssertionError("integrity_check attempted db.delete")

    monkeypatch.setattr(db_session, "delete", _no_delete)

    report = maintenance.integrity_check(db_session, upload_dir)
    assert ("f-missing", "gone.pdf") in report["missing_bytes_rows"]
    assert db_session.get(models.File, "f-missing") is not None


# ---------------------------------------------------------------------------
# CLI (manage.py maintenance) — dry-run default, --apply required for deletes
# ---------------------------------------------------------------------------

def test_cli_maintenance_dry_run_default(db_url, upload_dir, capsys):
    # Row with no bytes on disk (broken download), and orphaned bytes with no row.
    add_file_row_cli(db_url, "f-missing", "gone.pdf")
    orphan = upload_dir / "old-orphan.bin"
    orphan.write_bytes(b"x")
    age_file(orphan, hours=25)

    rc = manage.main(["maintenance", "--db-url", db_url, "--upload-dir", str(upload_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "gone.pdf" in out
    # dry-run changed nothing
    _assert_row_exists(db_url, "f-missing")


def test_cli_maintenance_apply_purges(db_url, upload_dir, tmp_path, capsys):
    add_file_row_cli(db_url, "f-missing", "gone.pdf")

    rc = manage.main([
        "maintenance", "--purge", "--apply", "--db-url", db_url, "--upload-dir", str(upload_dir),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "apply" in out
    _assert_row_missing(db_url, "f-missing")


def test_cli_maintenance_integrity_check_read_only(db_url, upload_dir, capsys):
    add_file_row_cli(db_url, "f-missing", "gone.pdf")

    rc = manage.main([
        "maintenance", "--integrity-check", "--db-url", db_url, "--upload-dir", str(upload_dir),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    # integrity-check never deletes
    _assert_row_exists(db_url, "f-missing")


def test_cli_maintenance_postgres_guard(db_url, upload_dir, capsys):
    rc = manage.main([
        "maintenance", "--db-url", "postgresql://u:***@localhost:5432/stw",
        "--upload-dir", str(upload_dir),
    ])
    assert rc == 2
    assert "--apply" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _engine(db_url):
    from sqlalchemy.orm import sessionmaker

    eng = database._make_engine(db_url)
    Base.metadata.create_all(bind=eng)
    return eng, sessionmaker(bind=eng)()


def add_file_row_cli(db_url, file_id: str, storage_key: str, age_days: float | None = None):
    eng, db = _engine(db_url)
    try:
        ensure_workspace(db)
        make_user(db, "user-1")
        created = None
        if age_days is not None:
            created = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age_days)).replace(tzinfo=None)
        db.add(models.File(
            id=file_id, workspace_id="ws-1", uploader_id="user-1",
            original_name=storage_key, storage_key=storage_key,
            mime_type="application/pdf", size_bytes=1, created_at=created,
        ))
        db.commit()
    finally:
        db.close()


def _assert_row_exists(db_url, file_id: str):
    eng, db = _engine(db_url)
    try:
        assert db.get(models.File, file_id) is not None
    finally:
        db.close()


def _assert_row_missing(db_url, file_id: str):
    eng, db = _engine(db_url)
    try:
        assert db.get(models.File, file_id) is None
    finally:
        db.close()
