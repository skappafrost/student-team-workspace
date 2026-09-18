"""Authenticated reads of uploaded file bytes (Stage 2.2, TA2-2).

``GET /uploads/{storage_key}`` used to be a bare StaticFiles mount: any LAN
peer with a URL could read any workspace's file. These tests pin the
replacement: the same URL shape now requires a valid session AND workspace
membership (mirroring ``GET /files/{id}``: guests 403, non-members 403,
anonymous 401, revoked sessions 401), and the legit download path still
works end-to-end against a real TestClient request.
"""

import io

import pytest
from fastapi.testclient import TestClient

import app as app_module
from conftest import as_user, clear_auth, make_user


def create_workspace(client: TestClient, db_session, user_id: str = "owner",
                      slug: str = "ws") -> dict:
    make_user(db_session, user_id)
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": "WS", "slug": slug, "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def upload_file(client: TestClient, workspace_id: str, filename: str = "report.pdf",
                content: bytes = b"file content") -> dict:
    resp = client.post(
        f"/workspaces/{workspace_id}/files",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch):
    """Point UPLOAD_DIR at a tmp dir (same redirect hook the router uses)."""
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", d)
    return d


@pytest.fixture()
def client(db_session, upload_dir):
    from database import get_db

    def _get_db_override():
        return db_session

    app_module.app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app_module.app)
    app_module.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Legit download path: member fetches the URL the API hands out
# ---------------------------------------------------------------------------

def test_member_download_works_end_to_end(db_session, client, upload_dir):
    ws = create_workspace(client, db_session, "owner")
    data = upload_file(client, ws["id"], "report.pdf", b"pdf-bytes-123")

    # The URL the API returns must download the exact uploaded bytes.
    resp = client.get(data["url"])
    assert resp.status_code == 200, resp.text
    assert resp.content == b"pdf-bytes-123"

    # Content metadata is preserved for browser handling.
    assert resp.headers["content-type"].startswith("application/pdf")


def test_download_content_disposition_preserves_original_name(db_session, client, upload_dir):
    ws = create_workspace(client, db_session, "owner")
    data = upload_file(client, ws["id"], "my report.pdf", b"x")

    resp = client.get(data["url"])
    assert resp.status_code == 200
    # FileResponse emits RFC 5987 (filename*=utf-8''...) for non-token names.
    disposition = resp.headers.get("content-disposition", "")
    assert disposition.startswith("attachment")
    assert "my%20report.pdf" in disposition


def test_guest_cannot_download_workspace_file(db_session, client, upload_dir):
    """Guests can join a workspace but, as on GET /files/{id} metadata reads,
    the guest role is below MEMBER — bytes are denied with 403."""
    ws = create_workspace(client, db_session, "owner")
    data = upload_file(client, ws["id"], "secret.pdf", b"secret")

    # Invite a guest via the real invite flow.
    invite = client.post(
        f"/workspaces/{ws['id']}/invites", json={"email": "guest@example.com", "role": "guest"}
    )
    assert invite.status_code == 201, invite.text
    token = invite.json()["token"]

    make_user(db_session, "guest-1", email="guest@example.com")
    clear_auth(client)
    as_user(client, "guest-1")
    acc = client.post("/invites/accept", json={"token": token})
    assert acc.status_code == 201, acc.text

    # Guest is a member but below MEMBER: bytes denied, mirroring /files/{id}.
    resp = client.get(data["url"])
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Deny paths: anonymous, cross-workspace, revoked session, unknown key
# ---------------------------------------------------------------------------

def test_anonymous_cannot_download(db_session, client, upload_dir):
    ws = create_workspace(client, db_session, "owner")
    data = upload_file(client, ws["id"], "secret.pdf", b"secret")

    clear_auth(client)
    resp = client.get(data["url"])
    assert resp.status_code == 401


def test_cross_workspace_user_cannot_download(db_session, client, upload_dir):
    ws_a = create_workspace(client, db_session, "owner-a", slug="ws-a")
    data = upload_file(client, ws_a["id"], "a-secret.pdf", b"a-secret")

    # owner-b has their own workspace but is NOT a member of ws-a.
    create_workspace(client, db_session, "owner-b", slug="ws-b")
    resp = client.get(data["url"])
    assert resp.status_code == 403


def test_revoked_session_cannot_download(db_session, client, upload_dir):
    # Register a real jti-backed session through the real endpoint.
    clear_auth(client)
    reg = client.post("/auth/register", json={"email": "dl@example.com", "password": "password123"})
    assert reg.status_code == 201, reg.text
    reg_data = reg.json()

    make_user(db_session, "owner", email="owner@example.com")
    as_user(client, "owner")
    ws = client.post("/workspaces", json={"name": "WS", "slug": "ws", "description": "x"})
    assert ws.status_code == 201, ws.text
    ws_id = ws.json()["id"]

    # Upload with the suite's (still-valid) session of the same user.
    data = upload_file(client, ws_id, "secret.pdf", b"secret")

    # Revoke the registered session, then hit the download URL with it.
    revoked_token = reg_data["access_token"]
    client.post("/auth/logout", headers={"Authorization": f"Bearer {revoked_token}"})
    resp = client.get(data["url"], headers={"Authorization": f"Bearer {revoked_token}"})
    assert resp.status_code == 401


def test_unknown_storage_key_returns_404(db_session, client, upload_dir):
    create_workspace(client, db_session, "owner")
    resp = client.get("/uploads/no-such-key.pdf")
    assert resp.status_code == 404


def test_missing_bytes_returns_404_not_500(db_session, client, upload_dir):
    """T008 contract preserved under the authenticated path: row exists,
    bytes gone → 404, never 500."""
    ws = create_workspace(client, db_session, "owner")
    data = upload_file(client, ws["id"], "ghost.pdf", b"bytes")
    stored = upload_dir / data["url"].split("/uploads/")[1]
    assert stored.exists()
    stored.unlink()

    resp = client.get(data["url"])
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Path traversal hardening on the read path
# ---------------------------------------------------------------------------

def test_traversal_key_is_rejected(db_session, client, upload_dir):
    create_workspace(client, db_session, "owner")
    for key in ("..%2f..%2fsecret.txt", "..\\..\\secret.txt", "..%5c..%5csecret.txt"):
        resp = client.get(f"/uploads/{key}")
        assert resp.status_code in (403, 404), (key, resp.status_code)
