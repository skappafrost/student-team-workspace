"""Tests for Project and Task CRUD endpoints with RBAC."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app, Role
from database import Base
from models import WorkspaceMember


# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_projects.db")
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


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def as_user(client: TestClient, user_id: str, role: str = Role.OWNER.value):
    client.headers["X-Test-User-Id"] = user_id
    client.headers["X-Test-User-Role"] = role


def clear_auth(client: TestClient):
    client.headers.pop("X-Test-User-Id", None)
    client.headers.pop("X-Test-User-Role", None)


def create_workspace(client: TestClient, user_id: str = "owner", name: str = "WS", slug: str = "ws"):
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201
    return resp.json()


def add_member(client, db_session, workspace_id, email, role, user_id):
    """Invite and accept an user into a workspace, return the new membership record."""
    owner_resp = client.post(
        f"/workspaces/{workspace_id}/invites",
        json={"email": email, "role": role},
    )
    assert owner_resp.status_code == 201, owner_resp.text
    token = owner_resp.json()["token"]

    # Create a real user row for the invitee so membership.user_id resolves
    from models import User
    new_user = User(id=user_id, email=email, display_name=user_id)
    db_session.add(new_user)
    db_session.commit()

    clear_auth(client)
    as_user(client, user_id, role)
    accept_resp = client.post("/invites/accept", json={"token": token})
    assert accept_resp.status_code == 201, accept_resp.text
    return accept_resp.json()


# ---------------------------------------------------------------------------
# Project CRUD happy paths
# ---------------------------------------------------------------------------

def test_create_project(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = client.post(
        f"/workspaces/{ws['id']}/projects",
        json={"name": "Science Fair", "description": "2026 project"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Science Fair"
    assert data["workspace_id"] == ws["id"]
    assert data["owner_id"] == "owner"
    assert data["status"] == "active"


def test_list_projects(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"})
    client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P2"})

    resp = client.get(f"/workspaces/{ws['id']}/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {p["name"] for p in data} == {"P1", "P2"}


def test_get_project(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    resp = client.get(f"/projects/{proj['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "P1"


def test_update_project_by_creator(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    resp = client.patch(f"/projects/{proj['id']}", json={"name": "P1 updated"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "P1 updated"


def test_delete_project_by_owner(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    resp = client.delete(f"/projects/{proj['id']}")
    assert resp.status_code == 204
    assert client.get(f"/projects/{proj['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Task CRUD happy paths
# ---------------------------------------------------------------------------

def test_create_task(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    resp = client.post(
        f"/projects/{proj['id']}/tasks",
        json={"title": "Task 1", "description": "desc", "priority": "high", "status": "todo", "position": 1.0},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Task 1"
    assert data["status"] == "todo"
    assert data["priority"] == "high"
    assert data["position"] == 1.0


def test_list_tasks_with_status_filter(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    client.post(f"/projects/{proj['id']}/tasks", json={"title": "T1", "status": "todo"})
    client.post(f"/projects/{proj['id']}/tasks", json={"title": "T2", "status": "doing"})
    client.post(f"/projects/{proj['id']}/tasks", json={"title": "T3", "status": "done"})

    resp = client.get(f"/projects/{proj['id']}/tasks?status=todo")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["title"] == "T1"


def test_update_task_status(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()
    task = client.post(f"/projects/{proj['id']}/tasks", json={"title": "T1"}).json()

    resp = client.patch(f"/tasks/{task['id']}", json={"status": "doing", "position": 2.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "doing"
    assert data["position"] == 2.0


def test_delete_task(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()
    task = client.post(f"/projects/{proj['id']}/tasks", json={"title": "T1"}).json()

    resp = client.delete(f"/tasks/{task['id']}")
    assert resp.status_code == 204
    assert client.get(f"/projects/{proj['id']}/tasks").json() == []


def test_task_position_ordering(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    client.post(f"/projects/{proj['id']}/tasks", json={"title": "B", "position": 2.0})
    client.post(f"/projects/{proj['id']}/tasks", json={"title": "A", "position": 1.0})
    client.post(f"/projects/{proj['id']}/tasks", json={"title": "C", "position": 3.0})

    resp = client.get(f"/projects/{proj['id']}/tasks")
    assert resp.status_code == 200
    titles = [t["title"] for t in resp.json()]
    assert titles == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# RBAC denials
# ---------------------------------------------------------------------------

def test_create_project_forbidden_for_guest(client, db_session):
    ws = create_workspace(client, "owner")
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user", Role.GUEST.value)
    resp = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "Bad"})
    assert resp.status_code == 403


def test_update_project_forbidden_for_member(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user", Role.MEMBER.value)
    resp = client.patch(f"/projects/{proj['id']}", json={"name": "Hacked"})
    assert resp.status_code == 403


def test_delete_project_forbidden_for_member(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user", Role.MEMBER.value)
    resp = client.delete(f"/projects/{proj['id']}")
    assert resp.status_code == 403


def test_admin_can_update_and_delete_any_project(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    add_member(client, db_session, ws["id"], "admin@example.com", Role.ADMIN.value, "admin-user")

    as_user(client, "admin-user", Role.ADMIN.value)
    resp = client.patch(f"/projects/{proj['id']}", json={"name": "Admin updated"})
    assert resp.status_code == 200
    assert client.delete(f"/projects/{proj['id']}").status_code == 204


def test_non_member_cannot_access_project(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()

    as_user(client, "stranger", Role.OWNER.value)
    resp = client.get(f"/projects/{proj['id']}")
    assert resp.status_code == 403


def test_task_rbac_member_can_update_any_task(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()
    task = client.post(f"/projects/{proj['id']}/tasks", json={"title": "T1"}).json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user", Role.MEMBER.value)
    resp = client.patch(f"/tasks/{task['id']}", json={"status": "doing"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "doing"


def test_task_delete_rbac_denied_for_member(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P1"}).json()
    task = client.post(f"/projects/{proj['id']}/tasks", json={"title": "T1"}).json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user", Role.MEMBER.value)
    resp = client.delete(f"/tasks/{task['id']}")
    assert resp.status_code == 403
