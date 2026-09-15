"""Per-workspace storage quota tests (TA2-3).

The quota is enforced at upload time on POST /workspaces/{id}/files: when the
workspace's stored bytes (SUM(files.size_bytes) for the workspace) plus the
incoming upload would exceed MAX_WORKSPACE_STORAGE_MB (default 512 MB,
0 disables the check), the upload is rejected with 413, no row is created and
no bytes are written. Deleting a file frees its bytes against the quota.
"""

import io

import pytest
from fastapi.testclient import TestClient

from config import Settings, settings
from conftest import as_user, make_user
from models import File

KB = 1024
MB = 1024 * 1024


def _upload(client: TestClient, ws_id: str, name: str, size_bytes: int, mime="application/pdf"):
    return client.post(
        f"/workspaces/{ws_id}/files",
        files={"file": (name, io.BytesIO(b"x" * size_bytes), mime)},
    )


def _make_workspace(client: TestClient, db_session) -> str:
    make_user(db_session, "owner")
    as_user(client, "owner")
    resp = client.post("/workspaces", json={"name": "WS", "slug": "ws", "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _stored_bytes(db_session, ws_id: str) -> int:
    return (
        db_session.query(File).filter(File.workspace_id == ws_id).with_entities(
            File.size_bytes
        )
    )


@pytest.fixture()
def quota_1mb(monkeypatch):
    monkeypatch.setattr(settings, "max_workspace_storage_mb", 1)


def test_quota_rejects_upload_over_limit(client, db_session, quota_1mb):
    ws_id = _make_workspace(client, db_session)

    ok = _upload(client, ws_id, "big.pdf", 700 * KB)
    assert ok.status_code == 201, ok.text

    rejected = _upload(client, ws_id, "over.pdf", 400 * KB)
    assert rejected.status_code == 413, rejected.text
    assert "quota" in rejected.json()["detail"].lower()

    # Rejected upload must not create a row (bytes are never written either —
    # the check runs before the write).
    rows = db_session.query(File).filter(File.workspace_id == ws_id).count()
    assert rows == 1

    # The endpoint still works for small uploads after a rejection.
    small = _upload(client, ws_id, "small.pdf", 10 * KB)
    assert small.status_code == 201, small.text


def test_quota_boundary_exact_fit_is_allowed(client, db_session, quota_1mb):
    ws_id = _make_workspace(client, db_session)

    first = _upload(client, ws_id, "half1.pdf", 512 * KB)
    assert first.status_code == 201, first.text

    # Second half lands exactly on the 1 MB boundary -> allowed.
    second = _upload(client, ws_id, "half2.pdf", 512 * KB)
    assert second.status_code == 201, second.text

    # One byte over the edge -> rejected.
    third = _upload(client, ws_id, "onebyte.pdf", 1)
    assert third.status_code == 413, third.text


def test_delete_frees_quota_space(client, db_session, quota_1mb):
    ws_id = _make_workspace(client, db_session)

    big = _upload(client, ws_id, "big.pdf", 700 * KB)
    assert big.status_code == 201, big.text
    file_id = big.json()["id"]

    rejected = _upload(client, ws_id, "more.pdf", 400 * KB)
    assert rejected.status_code == 413, rejected.text

    # Owner deletes the big file -> its bytes no longer count.
    deleted = client.delete(f"/files/{file_id}")
    assert deleted.status_code == 204, deleted.text

    again = _upload(client, ws_id, "more.pdf", 400 * KB)
    assert again.status_code == 201, again.text


def test_quota_zero_disables_the_check(client, db_session, monkeypatch):
    ws_id = _make_workspace(client, db_session)
    monkeypatch.setattr(settings, "max_workspace_storage_mb", 1)
    assert _upload(client, ws_id, "a.pdf", 600 * KB).status_code == 201

    monkeypatch.setattr(settings, "max_workspace_storage_mb", 0)
    # Would exceed the previous 1 MB quota, but 0 disables enforcement.
    assert _upload(client, ws_id, "b.pdf", 600 * KB).status_code == 201


def test_quota_is_per_workspace_not_global(client, db_session, quota_1mb):
    ws1 = _make_workspace(client, db_session)

    # Fill workspace 1 close to its quota.
    assert _upload(client, ws1, "fill.pdf", 900 * KB).status_code == 201

    # A second workspace starts from zero usage.
    as_user(client, "owner")
    resp = client.post("/workspaces", json={"name": "WS2", "slug": "ws2", "description": "x"})
    assert resp.status_code == 201, resp.text
    ws2 = resp.json()["id"]

    assert _upload(client, ws2, "other-ws.pdf", 900 * KB).status_code == 201
    # ...while workspace 1 is now over quota for anything non-trivial.
    assert _upload(client, ws1, "ws1-over.pdf", 200 * KB).status_code == 413


def test_max_workspace_storage_mb_env_wiring(monkeypatch):
    monkeypatch.delenv("MAX_WORKSPACE_STORAGE_MB", raising=False)
    assert Settings().max_workspace_storage_mb == 512  # documented default

    monkeypatch.setenv("MAX_WORKSPACE_STORAGE_MB", "2")
    assert Settings().max_workspace_storage_mb == 2

    monkeypatch.setenv("MAX_WORKSPACE_STORAGE_MB", "0")
    assert Settings().max_workspace_storage_mb == 0
