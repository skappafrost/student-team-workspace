"""Workspace invitation lifecycle tests using the FastAPI test client.

Previously these tests hit a live server at import time. They now use
TestClient with isolated test databases and real JWT authentication
(shared fixtures from conftest.py).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import as_user


def test_invite_lifecycle(client):
    owner_id = f"invite-owner-{uuid.uuid4().hex[:8]}"
    as_user(client, owner_id)

    slug = f"test-ws-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/workspaces",
        json={"name": "Test WS", "slug": slug, "description": "x"},
    )
    assert r.status_code == 201
    ws_id = r.json()["id"]

    r = client.get(f"/workspaces/{ws_id}/members")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "invitee@example.com", "role": "member"},
    )
    assert r.status_code == 201
    invite = r.json()
    invite_id = invite["id"]
    assert invite["role"] == "member"

    r = client.get(f"/workspaces/{ws_id}/invites")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.patch(
        f"/workspaces/{ws_id}/invites/{invite_id}",
        json={"role": "admin"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"

    r = client.delete(f"/workspaces/{ws_id}/invites/{invite_id}")
    assert r.status_code == 204

    r = client.get(f"/workspaces/{ws_id}/invites")
    assert r.status_code == 200
    assert r.json() == []


def test_duplicate_membership_prevention(client):
    owner_id = f"dup-owner-{uuid.uuid4().hex[:8]}"
    as_user(client, owner_id)
    slug = f"test-ws-{uuid.uuid4().hex[:8]}"
    r = client.post("/workspaces", json={"name": "Test WS", "slug": slug})
    assert r.status_code == 201
    ws_id = r.json()["id"]

    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(f"/workspaces/{ws_id}/invites", json={"email": email, "role": "member"})
    assert r.status_code == 201
    token1 = r.json()["token"]

    # Accept as user1
    user1_id = f"user1-{uuid.uuid4().hex[:8]}"
    as_user(client, user1_id)
    r = client.post("/invites/accept", json={"token": token1})
    assert r.status_code == 201

    # Second invite as owner
    as_user(client, owner_id)
    r = client.post(f"/workspaces/{ws_id}/invites", json={"email": email, "role": "member"})
    assert r.status_code == 201
    token2 = r.json()["token"]

    # Accept again as user1
    as_user(client, user1_id)
    r = client.post("/invites/accept", json={"token": token2})
    assert r.status_code == 409
    assert r.json()["detail"] == "User is already a member of this workspace"

    # The duplicate invite was consumed anyway (marked accepted) so it does not
    # linger as pending, and no second membership row was created.
    as_user(client, owner_id)
    r = client.get(f"/workspaces/{ws_id}/invites")
    assert r.status_code == 200
    assert r.json() == []

    r = client.get(f"/workspaces/{ws_id}/members")
    assert r.status_code == 200
    members = r.json()
    # owner + user1 exactly once each — no duplicate row for user1
    assert [m["user_id"] for m in members].count(user1_id) == 1
    assert [m["user_id"] for m in members].count(owner_id) == 1