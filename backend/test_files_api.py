"""Tests for File CRUD endpoints with RBAC."""

import io
import pytest
from fastapi.testclient import TestClient

from app import app, Role
from conftest import as_user, clear_auth, make_user





# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def create_workspace(client: TestClient, user_id: str = "owner", name: str = "WS", slug: str = "ws"):
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201
    return resp.json()


def add_member(client, db_session, workspace_id, email, role, user_id):
    """Invite and accept a user into a workspace, return the new membership record."""
    owner_resp = client.post(
        f"/workspaces/{workspace_id}/invites",
        json={"email": email, "role": role},
    )
    assert owner_resp.status_code == 201, owner_resp.text
    token = owner_resp.json()["token"]

    make_user(db_session, user_id, email=email)
    clear_auth(client)
    as_user(client, user_id)
    accept_resp = client.post("/invites/accept", json={"token": token})
    assert accept_resp.status_code == 201, accept_resp.text
    return accept_resp.json()


def upload_file(client, workspace_id, filename="report.pdf", content=b"file content", file_type="application/pdf"):
    return client.post(
        f"/workspaces/{workspace_id}/files",
        files={"file": (filename, io.BytesIO(content), file_type)},
    )


# ---------------------------------------------------------------------------
# File CRUD happy paths
# ---------------------------------------------------------------------------

def test_upload_file(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = upload_file(client, ws["id"], "report.pdf", b"pdf content")
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "report.pdf"
    assert data["type"] == "document"
    assert data["size"] == 11
    assert data["url"].startswith("/uploads/")
    assert data["uploaded_by"] == "owner"
    assert data["workspace_id"] == ws["id"]


def test_upload_image_file(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = upload_file(client, ws["id"], "photo.png", b"\x89PNG\r\n\x1a\n", "image/png")
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "photo.png"
    assert data["type"] == "image"


def test_list_files(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    upload_file(client, ws["id"], "a.pdf", b"a")
    upload_file(client, ws["id"], "b.pdf", b"b")

    resp = client.get(f"/workspaces/{ws['id']}/files")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = [f["name"] for f in data]
    assert "a.pdf" in names
    assert "b.pdf" in names


def test_get_file(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    file_id = upload_file(client, ws["id"], "report.pdf", b"pdf content").json()["id"]

    resp = client.get(f"/files/{file_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "report.pdf"
    assert data["workspace_id"] == ws["id"]


def test_update_file(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    file_id = upload_file(client, ws["id"], "old.pdf", b"content").json()["id"]

    resp = client.patch(f"/files/{file_id}", json={"name": "new.pdf"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "new.pdf"
    assert data["type"] == "document"


def test_delete_file(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    file_id = upload_file(client, ws["id"], "trash.pdf", b"x").json()["id"]

    resp = client.delete(f"/files/{file_id}")
    assert resp.status_code == 204
    assert client.get(f"/files/{file_id}").status_code == 404


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_member_can_upload_and_update_own_file(client, db_session):
    ws = create_workspace(client, "owner")
    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    file_id = upload_file(client, ws["id"], "member.pdf", b"x").json()["id"]

    update_resp = client.patch(f"/files/{file_id}", json={"name": "updated.pdf"})
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "updated.pdf"


def test_member_cannot_update_others_file(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    file_id = upload_file(client, ws["id"], "owner.pdf", b"x").json()["id"]

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")
    as_user(client, "member-user")
    resp = client.patch(f"/files/{file_id}", json={"name": "hacked.pdf"})
    assert resp.status_code == 403


def test_admin_can_update_and_delete_any_file(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    file_id = upload_file(client, ws["id"], "target.pdf", b"x").json()["id"]

    add_member(client, db_session, ws["id"], "admin@example.com", Role.ADMIN.value, "admin-user")
    as_user(client, "admin-user")
    update_resp = client.patch(f"/files/{file_id}", json={"name": "admin.pdf"})
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "admin.pdf"
    assert client.delete(f"/files/{file_id}").status_code == 204


def test_guest_cannot_upload_file(client, db_session):
    ws = create_workspace(client, "owner")
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user")
    resp = upload_file(client, ws["id"], "guest.pdf", b"x")
    assert resp.status_code == 403


def test_guest_cannot_list_files(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    upload_file(client, ws["id"], "public.pdf", b"x")

    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")
    as_user(client, "guest-user")
    resp = client.get(f"/workspaces/{ws['id']}/files")
    assert resp.status_code == 403


def test_non_member_cannot_access_files(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    file_id = upload_file(client, ws["id"], "secret.pdf", b"x").json()["id"]

    as_user(client, "stranger")
    resp_get = client.get(f"/files/{file_id}")
    assert resp_get.status_code == 403

    resp_list = client.get(f"/workspaces/{ws['id']}/files")
    assert resp_list.status_code == 403


# ---------------------------------------------------------------------------
# Validation / error cases
# ---------------------------------------------------------------------------

def test_get_file_not_found(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = client.get("/files/nonexistent-uuid")
    assert resp.status_code == 404


def test_update_file_not_found(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = client.patch("/files/nonexistent-uuid", json={"name": "x.pdf"})
    assert resp.status_code == 404


def test_delete_file_not_found(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = client.delete("/files/nonexistent-uuid")
    assert resp.status_code == 404


def test_upload_without_file_returns_422(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = client.post(f"/workspaces/{ws['id']}/files")
    assert resp.status_code == 422
