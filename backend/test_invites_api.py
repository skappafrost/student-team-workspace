"""Workspace invitation lifecycle tests using the FastAPI test client.

Previously these tests hit a live server at import time. They now use
TestClient with isolated test databases and the ``X-Test-User-Id`` header.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app, Base


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_invites.db")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    from database import get_db

    def _get_db_override():
        return db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as_user(client: TestClient, user_id: str, role: str = "owner"):
    client.headers["X-Test-User-Id"] = user_id
    client.headers["X-Test-User-Role"] = role


def test_invite_lifecycle(client):
    owner_id = f"invite-owner-{uuid.uuid4().hex[:8]}"
    _as_user(client, owner_id)

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
    _as_user(client, owner_id)
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
    _as_user(client, user1_id)
    r = client.post("/invites/accept", json={"token": token1})
    assert r.status_code == 201

    # Second invite as owner
    _as_user(client, owner_id)
    r = client.post(f"/workspaces/{ws_id}/invites", json={"email": email, "role": "member"})
    assert r.status_code == 201
    token2 = r.json()["token"]

    # Accept again as user1
    _as_user(client, user1_id)
    r = client.post("/invites/accept", json={"token": token2})
    assert r.status_code == 409
    assert r.json()["detail"] == "User is already a member of this workspace"