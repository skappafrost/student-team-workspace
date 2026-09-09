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
