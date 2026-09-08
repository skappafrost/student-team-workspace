"""Tests for Notification CRUD endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Role, app
from database import Base, get_db
from models import User

# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_notifications.db", echo=False)
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
    def _get_db_override():
        return db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def as_user(client: TestClient, user_id: str, role: str = Role.OWNER.value):
    client.headers["X-Test-User-Id"] = user_id
    client.headers["X-Test-User-Role"] = role


def create_workspace(
    client: TestClient, user_id: str = "owner", name: str = "WS", slug: str = "ws"
):
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201
    return resp.json()


def create_user(client, db_session, user_id, email):
    user = User(id=user_id, email=email, display_name=user_id)
    db_session.add(user)
    db_session.commit()
    return user


# ---------------------------------------------------------------------------
# Notification CRUD happy paths
# ---------------------------------------------------------------------------


def test_create_notification(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "target-user", "target@example.com")
    as_user(client, "owner")
    resp = client.post(
        "/notifications",
        json={
            "user_id": "target-user",
            "type": "task-assigned",
            "title": "You were assigned a task",
            "content": "Task 'W7-2' was assigned to you",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_id"] == "target-user"
    assert data["type"] == "task-assigned"
    assert data["title"] == "You were assigned a task"
    assert data["content"] == "Task 'W7-2' was assigned to you"
    assert data["read"] is False
    assert "id" in data
    assert "created_at" in data


def test_list_notifications_for_current_user(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "target-user", "target@example.com")
    as_user(client, "owner")

    client.post(
        "/notifications",
        json={
            "user_id": "target-user",
            "type": "mention",
            "title": "Mentioned you",
            "content": "Hello!",
        },
    )
    client.post(
        "/notifications",
        json={
            "user_id": "target-user",
            "type": "file-upload",
            "title": "File uploaded",
            "content": "A file was uploaded",
        },
    )

    as_user(client, "target-user")
    resp = client.get("/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["type"] == "mention"
    assert data[1]["type"] == "file-upload"


def test_get_notification(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "target-user", "target@example.com")
    as_user(client, "owner")
    n = client.post(
        "/notifications",
        json={"user_id": "target-user", "type": "mention", "title": "Read me"},
    ).json()

    as_user(client, "target-user")
    resp = client.get(f"/notifications/{n['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == n["id"]


def test_mark_notification_read(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "target-user", "target@example.com")
    as_user(client, "owner")
    n = client.post(
        "/notifications",
        json={"user_id": "target-user", "type": "mention", "title": "Read me"},
    ).json()

    as_user(client, "target-user")
    resp = client.patch(f"/notifications/{n['id']}", json={"read": True})
    assert resp.status_code == 200
    assert resp.json()["read"] is True

    resp = client.patch(f"/notifications/{n['id']}", json={"read": False})
    assert resp.status_code == 200
    assert resp.json()["read"] is False


def test_notification_read_toggle(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "target-user", "target@example.com")
    as_user(client, "owner")
    n = client.post(
        "/notifications",
        json={"user_id": "target-user", "type": "mention", "title": "Read me"},
    ).json()

    as_user(client, "target-user")
    resp = client.patch(f"/notifications/{n['id']}", json={"read": True})
    assert resp.status_code == 200
    assert resp.json()["read"] is True

    resp = client.patch(f"/notifications/{n['id']}", json={"read": False})
    assert resp.status_code == 200
    assert resp.json()["read"] is False


def test_list_unread_only(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "target-user", "target@example.com")
    as_user(client, "owner")

    n1 = client.post(
        "/notifications",
        json={"user_id": "target-user", "type": "mention", "title": "One"},
    ).json()
    client.post(
        "/notifications",
        json={"user_id": "target-user", "type": "mention", "title": "Two"},
    )

    as_user(client, "target-user")
    client.patch(f"/notifications/{n1['id']}", json={"read": True})

    resp = client.get("/notifications?unread_only=true")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Two"


def test_delete_notification(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "target-user", "target@example.com")
    as_user(client, "owner")
    n = client.post(
        "/notifications",
        json={"user_id": "target-user", "type": "mention", "title": "Delete me"},
    ).json()

    as_user(client, "target-user")
    resp = client.delete(f"/notifications/{n['id']}")
    assert resp.status_code == 204
    assert client.get(f"/notifications/{n['id']}").status_code == 404


# ---------------------------------------------------------------------------
# RBAC / security
# ---------------------------------------------------------------------------


def test_user_cannot_access_others_notifications(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "user-a", "a@example.com")
    create_user(client, db_session, "user-b", "b@example.com")

    as_user(client, "owner")
    n = client.post(
        "/notifications",
        json={"user_id": "user-a", "type": "mention", "title": "Private"},
    ).json()

    as_user(client, "user-b")
    resp = client.patch(f"/notifications/{n['id']}", json={"read": True})
    assert resp.status_code == 403

    resp = client.delete(f"/notifications/{n['id']}")
    assert resp.status_code == 403


def test_cannot_create_notification_for_missing_user(client):
    create_workspace(client, "owner")
    as_user(client, "owner")
    resp = client.post(
        "/notifications",
        json={"user_id": "missing-user", "type": "mention", "title": "No one"},
    )
    assert resp.status_code == 404


def test_invalid_notification_type_rejected(client, db_session):
    create_workspace(client, "owner")
    create_user(client, db_session, "target-user", "target@example.com")
    as_user(client, "owner")
    resp = client.post(
        "/notifications",
        json={"user_id": "target-user", "type": "invalid-type", "title": "Bad"},
    )
    assert resp.status_code == 422
