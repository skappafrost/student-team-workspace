"""Workspace API tests using the FastAPI test client.

Previously these tests hit a live server at import time, which caused
non-deterministic failures when the server was down or when test data
conflicted. They now use TestClient and the test-only ``X-Test-User-Id``
header so the full suite is isolated and hermetic.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app, Base


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_workspace.db")
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


def test_workspace_members_flow(client):
    owner_id = f"ws-owner-{uuid.uuid4().hex[:8]}"
    _as_user(client, owner_id)

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
