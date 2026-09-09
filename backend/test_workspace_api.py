"""Workspace API tests using the FastAPI test client.

Previously these tests hit a live server at import time, which caused
non-deterministic failures when the server was down or when test data
conflicted. They now use TestClient and real JWT authentication (shared
fixtures from conftest.py) so the full suite is isolated and hermetic.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import as_user


def test_workspace_members_flow(client):
    owner_id = f"ws-owner-{uuid.uuid4().hex[:8]}"
    as_user(client, owner_id)

    slug = f"test-ws-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/workspaces",
        json={"name": "Test WS", "slug": slug, "description": "x"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test WS"
    ws_id = data["id"]

    r = client.get(f"/workspaces/{ws_id}/members")
    assert r.status_code == 200
    members = r.json()
    assert len(members) == 1
    assert members[0]["user_id"] == owner_id

    r = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "invitee@example.com", "role": "member"},
    )
    assert r.status_code == 201
    invite = r.json()
    assert invite["email"] == "invitee@example.com"
    assert invite["role"] == "member"

    r = client.get(f"/workspaces/{ws_id}/invites")
    assert r.status_code == 200
    invites = r.json()
    assert len(invites) == 1
    assert invites[0]["email"] == "invitee@example.com"
