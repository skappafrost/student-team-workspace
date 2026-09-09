"""Tests for Channel and Message CRUD endpoints with RBAC."""

import pytest
from fastapi.testclient import TestClient

from app import app, Role
from conftest import as_user, clear_auth, make_user





# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def create_workspace(client: TestClient, db_session, user_id: str = "owner", name: str = "WS", slug: str = "ws"):
    # Ensure the test user exists with the expected id/display_name.
    make_user(db_session, user_id)
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


# ---------------------------------------------------------------------------
# Channel CRUD happy paths
# ---------------------------------------------------------------------------

def test_create_channel(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "general"
    assert data["type"] == "general"
    assert data["workspace_id"] == ws["id"]
    assert data["created_by"] == "owner"


def test_list_channels(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/channels", json={"name": "c1", "type": "general"})
    client.post(f"/workspaces/{ws['id']}/channels", json={"name": "c2", "type": "project"})

    resp = client.get(f"/workspaces/{ws['id']}/channels")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {c["name"] for c in data} == {"c1", "c2"}


# ---------------------------------------------------------------------------
# Message CRUD happy paths
# ---------------------------------------------------------------------------

def test_send_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()

    resp = client.post(f"/channels/{channel['id']}/messages", json={"content": "Hello!"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Hello!"
    assert data["author_id"] == "owner"
    assert data["author_name"] == "owner"
    assert data["channel_id"] == channel["id"]


def test_list_messages(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    client.post(f"/channels/{channel['id']}/messages", json={"content": "first"})
    client.post(f"/channels/{channel['id']}/messages", json={"content": "second"})

    resp = client.get(f"/channels/{channel['id']}/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["content"] == "first"
    assert data[1]["content"] == "second"
    assert all("author_name" in m and m["author_name"] == "owner" for m in data)


def test_update_message_by_owner(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "original"}).json()

    resp = client.patch(f"/messages/{message['id']}", json={"content": "updated"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "updated"


def test_delete_message_by_owner(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "to delete"}).json()

    resp = client.delete(f"/messages/{message['id']}")
    assert resp.status_code == 204
    assert client.get(f"/channels/{channel['id']}/messages").json() == []


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_member_can_create_channel_and_send_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "member-channel", "type": "general"})
    assert resp.status_code == 201
    channel_id = resp.json()["id"]

    resp = client.post(f"/channels/{channel_id}/messages", json={"content": "hi"})
    assert resp.status_code == 201


def test_guest_cannot_create_channel(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "bad", "type": "general"})
    # Guest is a workspace member but lacks write permissions in this implementation
    assert resp.status_code == 403


def test_guest_cannot_send_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user")
    resp = client.post(f"/channels/{channel['id']}/messages", json={"content": "hi"})
    assert resp.status_code == 403


def test_non_member_cannot_list_channels(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"})

    as_user(client, "stranger")
    resp = client.get(f"/workspaces/{ws['id']}/channels")
    assert resp.status_code == 403


def test_member_cannot_update_others_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "owner msg"}).json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = client.patch(f"/messages/{message['id']}", json={"content": "hacked"})
    assert resp.status_code == 403


def test_admin_can_update_and_delete_any_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "owner msg"}).json()

    add_member(client, db_session, ws["id"], "admin@example.com", Role.ADMIN.value, "admin-user")

    as_user(client, "admin-user")
    update_resp = client.patch(f"/messages/{message['id']}", json={"content": "admin updated"})
    assert update_resp.status_code == 200
    assert update_resp.json()["content"] == "admin updated"
    assert client.delete(f"/messages/{message['id']}").status_code == 204


def test_private_channel_requires_admin_to_create(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "private", "type": "private"})
    assert resp.status_code == 403

    as_user(client, "owner")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "private", "type": "private"})
    assert resp.status_code == 201
    assert resp.json()["is_private"] is True
