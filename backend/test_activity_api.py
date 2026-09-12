"""Tests for the notification service + workspace activity feed (R03)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app
from models import User, WorkspaceMembership


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_activity.db", echo=False)
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

    from database import get_db

    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(client: TestClient, user_id: str, role: str = Role.OWNER.value):
    client.headers["X-Test-User-Id"] = user_id
    client.headers["X-Test-User-Role"] = role


@pytest.fixture(scope="function")
def ws_id(client, db_session):
    db_session.add(User(id="u1", email="u1@example.com", display_name="Owner One"))
    db_session.add(User(id="u2", email="u2@example.com", display_name="Member Two"))
    db_session.commit()
    as_user(client, "u1")
    wid = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()["id"]
    db_session.add(WorkspaceMembership(workspace_id=wid, user_id="u2", role=Role.MEMBER.value))
    db_session.commit()
    return wid


def test_activity_recorded_on_task_create(client, ws_id):
    as_user(client, "u1")
    proj = client.post(
        f"/workspaces/{ws_id}/projects", json={"name": "P1"}
    ).json()
    client.post(f"/projects/{proj['id']}/tasks", json={"title": "T1"})

    feed = client.get(f"/workspaces/{ws_id}/activity").json()
    assert any(a["verb"] == "created task" and a["target_label"] == "T1" for a in feed)
    entry = next(a for a in feed if a["target_label"] == "T1")
    assert entry["actor_name"] == "Owner One"


def test_assign_notifies_assignee_with_link(client, ws_id):
    as_user(client, "u1")
    proj = client.post(f"/workspaces/{ws_id}/projects", json={"name": "P1"}).json()
    resp = client.post(
        f"/projects/{proj['id']}/tasks", json={"title": "T1", "assignee_id": "u2"}
    )
    assert resp.status_code == 201

    as_user(client, "u2", Role.MEMBER.value)
    notifs = client.get("/notifications").json()
    hit = [n for n in notifs if n["type"] == "task-assigned"]
    assert len(hit) == 1
    assert hit[0]["link"] == f"/dashboard/projects/{proj['id']}"
    assert "T1" in hit[0]["title"]


def test_no_notification_when_self_assigned(client, ws_id):
    as_user(client, "u1")
    proj = client.post(f"/workspaces/{ws_id}/projects", json={"name": "P1"}).json()
    client.post(f"/projects/{proj['id']}/tasks", json={"title": "T1", "assignee_id": "u1"})

    notifs = client.get("/notifications").json()
    assert not [n for n in notifs if n["type"] == "task-assigned"]


def test_activity_for_message_event_page(client, ws_id):
    as_user(client, "u1")
    ch = client.post(f"/workspaces/{ws_id}/channels", json={"name": "general"}).json()
    client.post(f"/channels/{ch['id']}/messages", json={"content": "hello"})
    client.post(
        f"/workspaces/{ws_id}/events",
        json={"title": "Sync", "start_at": "2026-09-15T09:00:00"},
    )
    client.post(
        f"/workspaces/{ws_id}/pages", json={"title": "Guide", "slug": "guide"}
    )

    feed = client.get(f"/workspaces/{ws_id}/activity").json()
    verbs = {a["verb"] for a in feed}
    assert {"posted in", "created event", "created page"} <= verbs


def test_activity_requires_membership(client, ws_id):
    as_user(client, "u1")
    client.post(
        f"/workspaces/{ws_id}/pages", json={"title": "Guide", "slug": "guide"}
    )
    # outsider
    as_user(client, "outsider", Role.MEMBER.value)
    resp = client.get(f"/workspaces/{ws_id}/activity")
    assert resp.status_code == 403
