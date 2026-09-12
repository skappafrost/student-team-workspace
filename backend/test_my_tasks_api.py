"""Tests for GET /users/me/tasks (F07 global deadlines)."""

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app
from models import User


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_mytasks.db", echo=False)
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


def _setup(client, db_session):
    db_session.add(User(id="u1", email="u1@example.com", display_name="u1"))
    db_session.commit()
    as_user(client, "u1")
    ws = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()
    proj = client.post(
        f"/workspaces/{ws['id']}/projects", json={"name": "Midterm"}
    ).json()
    return ws, proj


def _add_task(client, proj_id, title, due_in_days=None, assignee="u1"):
    payload = {"title": title, "assignee_id": assignee}
    if due_in_days is not None:
        due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=due_in_days)
        payload["due_at"] = due.isoformat()
    resp = client.post(f"/projects/{proj_id}/tasks", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_my_tasks_returns_assigned_only_with_names(client, db_session):
    _, proj = _setup(client, db_session)
    _add_task(client, proj["id"], "Mine", due_in_days=2)
    _add_task(client, proj["id"], "Not mine", due_in_days=2, assignee=None)

    resp = client.get("/users/me/tasks")
    assert resp.status_code == 200
    tasks = resp.json()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Mine"
    assert tasks[0]["project_name"] == "Midterm"
    assert tasks[0]["workspace_name"] == "WS"
    assert tasks[0]["due_at"] is not None


def test_my_tasks_due_buckets(client, db_session):
    _, proj = _setup(client, db_session)
    _add_task(client, proj["id"], "overdue", due_in_days=-1)
    # "today" = later today (2h from now); due_in_days=0 would be microseconds past.
    today_due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    resp = client.post(
        f"/projects/{proj['id']}/tasks",
        json={"title": "today", "assignee_id": "u1", "due_at": today_due.isoformat()},
    )
    assert resp.status_code == 201
    _add_task(client, proj["id"], "this week", due_in_days=3)
    _add_task(client, proj["id"], "later", due_in_days=30)
    _add_task(client, proj["id"], "no date")

    all_tasks = client.get("/users/me/tasks").json()
    assert len(all_tasks) == 5
    # Sorted by due date, undated last.
    assert [t["title"] for t in all_tasks] == ["overdue", "today", "this week", "later", "no date"]

    overdue = client.get("/users/me/tasks", params={"due": "overdue"}).json()
    assert [t["title"] for t in overdue] == ["overdue"]

    today = client.get("/users/me/tasks", params={"due": "today"}).json()
    assert [t["title"] for t in today] == ["today"]

    week = client.get("/users/me/tasks", params={"due": "week"}).json()
    assert [t["title"] for t in week] == ["this week"]

    later = client.get("/users/me/tasks", params={"due": "later"}).json()
    assert [t["title"] for t in later] == ["later"]

    none_ = client.get("/users/me/tasks", params={"due": "none"}).json()
    assert [t["title"] for t in none_] == ["no date"]


def test_my_tasks_status_filter(client, db_session):
    _, proj = _setup(client, db_session)
    t = _add_task(client, proj["id"], "done one", due_in_days=1)
    client.patch(f"/tasks/{t['id']}", json={"status": "done"})
    _add_task(client, proj["id"], "open one", due_in_days=1)

    done = client.get("/users/me/tasks", params={"status": "done"}).json()
    assert [x["title"] for x in done] == ["done one"]


def test_due_at_roundtrip_on_create_and_update(client, db_session):
    _, proj = _setup(client, db_session)
    t = _add_task(client, proj["id"], "x", due_in_days=5)
    assert t["due_at"] is not None

    new_due = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)).isoformat()
    updated = client.patch(f"/tasks/{t['id']}", json={"due_at": new_due}).json()
    assert updated["due_at"][:10] == new_due[:10]
