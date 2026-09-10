"""Tests for file-delete correctness and the orphan-upload sweeper (T040).

Covers:
- delete_file: commit-then-unlink ordering (a failed commit must leave the
  bytes on disk), and unlink failure on Windows (row still deleted, bytes
  left for the sweeper).
- maintenance.purge_orphans: dry-run vs apply, row cleanup for missing
  bytes, unlink of old orphaned files, resilience to unlink errors, and the
  PostgreSQL guard in the CLI.
- The /uploads content path returns 404 (not 500) for missing bytes (T008).
"""

import io
import os
import time
from pathlib import Path

import pytest
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

import app as app_module
import database
import maintenance
import models
from app import Role
from conftest import make_user, as_user
from database import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session(tmp_path):
    # Isolated engine (FK pragma ON via _make_engine). Must NOT call
    # database.set_db_url(): rebinding the global engine leaks into later
    # tests sharing this process (test pollution under T014 enforcement).
    from sqlalchemy.orm import sessionmaker
    eng = database._make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(bind=eng)
    db = sessionmaker(bind=eng)()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=eng)


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch):
    """Point UPLOAD_DIR (and the /uploads static mount) at a tmp directory."""
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", d)
    # The static mount captured the default ./uploads dir at import time, so
    # swap the route to serve from the tmp dir instead.
    app_module.app.router.routes[:] = [
        r for r in app_module.app.router.routes if getattr(r, "name", None) != "uploads"
    ]
    app_module.app.mount("/uploads", StaticFiles(directory=str(d)), name="uploads")
    return d


@pytest.fixture()
def client(db_session, upload_dir):
    def _get_db_override():
        return db_session

    app_module.app.dependency_overrides[database.get_db] = _get_db_override
    yield TestClient(app_module.app)
    app_module.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_workspace(db, workspace_id: str = "ws-1"):
    """Get-or-create a workspace row so FK-enforcing DBs stay happy (T014)."""
    ws = db.get(models.Workspace, workspace_id)
    if ws is None:
        ws = models.Workspace(id=workspace_id, name="WS", slug=workspace_id)
        db.add(ws)
        db.commit()
    return ws


def create_workspace(client: TestClient, db_session=None, user_id: str = "owner", name: str = "WS", slug: str = "ws"):
    if db_session is not None:
        make_user(db_session, user_id)
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def upload_file(client: TestClient, workspace_id: str, filename: str = "report.pdf", content: bytes = b"file content"):
    return client.post(
        f"/workspaces/{workspace_id}/files",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
    )


def storage_key_of(data: dict) -> str:
    return data["url"].split("/uploads/")[1]


def age_file(path: Path, hours: float):
    """Backdate a file's mtime so the sweeper treats it as an orphan."""
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


def add_file_row(db, file_id: str, storage_key: str):
    ensure_workspace(db)
    make_user(db, "user-1")
    db.add(models.File(
        id=file_id,
        workspace_id="ws-1",
        uploader_id="user-1",
        original_name=storage_key,
        storage_key=storage_key,
        mime_type="application/pdf",
        size_bytes=1,
    ))
    db.commit()


# ---------------------------------------------------------------------------
# delete_file: commit-then-unlink ordering
# ---------------------------------------------------------------------------

def test_delete_file_commit_failure_keeps_bytes_and_returns_500(db_session, client, upload_dir):
    ws = create_workspace(client, db_session)
    as_user(client, "owner")
    resp = upload_file(client, ws["id"], "crash.pdf", b"bytes")
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]
    stored = upload_dir / storage_key_of(resp.json())
    assert stored.exists()

    def _boom():
        raise RuntimeError("injected commit failure")

    db_session.commit = _boom
    strict_client = TestClient(app_module.app, raise_server_exceptions=False)
    strict_client.headers.update(client.headers)
    resp = strict_client.delete(f"/files/{file_id}")
    assert resp.status_code == 500

    # Bytes must survive a failed commit: a row pointing at missing bytes
    # would break downloads, an orphaned upload is reclaimable.
    assert stored.exists()
    db_session.rollback()
    assert db_session.get(models.File, file_id) is not None


def test_delete_file_unlink_failure_still_deletes_row(db_session, client, upload_dir, monkeypatch):
    ws = create_workspace(client, db_session)
    as_user(client, "owner")
    resp = upload_file(client, ws["id"], "locked.pdf", b"bytes")
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]
    storage_key = storage_key_of(resp.json())
    stored = upload_dir / storage_key
    assert stored.exists()

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name == storage_key:
            raise OSError(13, "Permission denied: file is in use")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    assert client.delete(f"/files/{file_id}").status_code == 204
    # Row is gone; the bytes are left for the next sweeper run (Windows edge case).
    assert db_session.get(models.File, file_id) is None
    assert stored.exists()


# ---------------------------------------------------------------------------
# /uploads content path: 404 for missing bytes (T008)
# ---------------------------------------------------------------------------

def test_missing_upload_bytes_return_404_not_500(db_session, client, upload_dir):
    ws = create_workspace(client, db_session)
    as_user(client, "owner")
    resp = upload_file(client, ws["id"], "ghost.pdf", b"bytes")
    assert resp.status_code == 201, resp.text
    stored = upload_dir / storage_key_of(resp.json())
    assert stored.exists()

    stored.unlink()
    resp = client.get(f"/uploads/{stored.name}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# maintenance.purge_orphans
# ---------------------------------------------------------------------------

def test_purge_orphans_dry_run_reports_without_changing(db_session, upload_dir):
    add_file_row(db_session, "f-missing", "gone.pdf")
    add_file_row(db_session, "f-present", "kept.pdf")
    (upload_dir / "kept.pdf").write_bytes(b"x")

    old_orphan = upload_dir / "old-orphan.bin"
    old_orphan.write_bytes(b"x")
    age_file(old_orphan, hours=25)

    fresh_orphan = upload_dir / "fresh-orphan.bin"
    fresh_orphan.write_bytes(b"x")

    report = maintenance.purge_orphans(db_session, upload_dir, apply=False)

    assert report["apply"] is False
    assert ("f-missing", "gone.pdf") in report["missing_bytes_rows"]
    assert report["orphan_files"] == ["old-orphan.bin"]
    assert report["skipped_fresh_files"] == ["fresh-orphan.bin"]
    assert report["dropped_rows"] == []
    assert report["unlinked_files"] == []
    assert report["unlink_errors"] == []

    # Nothing changed in dry-run mode.
    assert db_session.get(models.File, "f-missing") is not None
    assert old_orphan.exists()
    assert fresh_orphan.exists()
    assert (upload_dir / "kept.pdf").exists()


def test_purge_orphans_apply_drops_rows_and_unlinks_old_files(db_session, upload_dir):
    add_file_row(db_session, "f-missing", "gone.pdf")
    add_file_row(db_session, "f-present", "kept.pdf")
    (upload_dir / "kept.pdf").write_bytes(b"x")

    old_orphan = upload_dir / "old-orphan.bin"
    old_orphan.write_bytes(b"x")
    age_file(old_orphan, hours=25)

    fresh_orphan = upload_dir / "fresh-orphan.bin"
    fresh_orphan.write_bytes(b"x")

    report = maintenance.purge_orphans(db_session, upload_dir, apply=True)

    assert report["dropped_rows"] == ["gone.pdf"]
    assert report["unlinked_files"] == ["old-orphan.bin"]
    assert db_session.get(models.File, "f-missing") is None
    assert db_session.get(models.File, "f-present") is not None
    assert not old_orphan.exists()
    assert fresh_orphan.exists()
    assert (upload_dir / "kept.pdf").exists()


def test_purge_orphans_apply_survives_unlink_errors(db_session, upload_dir, monkeypatch):
    add_file_row(db_session, "f-missing", "gone.pdf")
    old_orphan = upload_dir / "old-orphan.bin"
    old_orphan.write_bytes(b"x")
    age_file(old_orphan, hours=25)

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "old-orphan.bin":
            raise OSError("file is in use")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    report = maintenance.purge_orphans(db_session, upload_dir, apply=True)

    assert report["dropped_rows"] == ["gone.pdf"]
    assert report["unlink_errors"] == [("old-orphan.bin", "file is in use")]
    # Row cleanup still applied; the locked bytes are left for a later run.
    assert db_session.get(models.File, "f-missing") is None
    assert old_orphan.exists()


# ---------------------------------------------------------------------------
# maintenance CLI
# ---------------------------------------------------------------------------

def test_purge_cli_refuses_postgres_without_apply(capsys):
    rc = maintenance.main(["purge-orphans", "--db-url", "postgresql://u:p@localhost:5432/stw"])
    assert rc == 2
    assert "--apply" in capsys.readouterr().err


def test_purge_cli_refuses_missing_upload_dir(capsys, tmp_path):
    rc = maintenance.main([
        "purge-orphans",
        "--db-url", f"sqlite:///{tmp_path / 'empty.db'}",
        "--upload-dir", str(tmp_path / "no-such-dir"),
    ])
    assert rc == 2
    assert "Upload directory" in capsys.readouterr().err


def test_purge_cli_refuses_missing_files_table(capsys, tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    rc = maintenance.main([
        "purge-orphans",
        "--db-url", f"sqlite:///{tmp_path / 'empty.db'}",
        "--upload-dir", str(upload_dir),
    ])
    assert rc == 2
    assert "files' table" in capsys.readouterr().err


def test_purge_cli_dry_run_runs_on_sqlite(db_session, upload_dir, capsys, tmp_path):
    # The db_session fixture uses an isolated tmp sqlite db: pass its URL
    # explicitly (same formula as the fixture) since the CLI reads --db-url.
    add_file_row(db_session, "f-missing", "gone.pdf")

    rc = maintenance.main([
        "purge-orphans",
        "--db-url", f"sqlite:///{tmp_path / 'test.db'}",
        "--upload-dir", str(upload_dir),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "gone.pdf" in out
    assert "dry-run" in out.lower() or "would" in out.lower()
    assert db_session.get(models.File, "f-missing") is not None
