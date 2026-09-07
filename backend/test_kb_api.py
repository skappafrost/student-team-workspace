"""Tests for Knowledge Base Page CRUD endpoints with RBAC."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app, Role
from database import Base
from models import User


# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_kb.db", echo=False)
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
    """Invite and accept a user into a workspace, return the new membership record."""
    owner_resp = client.post(
        f"/workspaces/{workspace_id}/invites",
        json={"email": email, "role": role},
    )
    assert owner_resp.status_code == 201, owner_resp.text
    token = owner_resp.json()["token"]

    new_user = User(id=user_id, email=email, display_name=user_id)
    db_session.add(new_user)
    db_session.commit()

    clear_auth(client)
    as_user(client, user_id, role)
    accept_resp = client.post("/invites/accept", json={"token": token})
    assert accept_resp.status_code == 201, accept_resp.text
    return accept_resp.json()


# ---------------------------------------------------------------------------
# Page CRUD happy paths
# ---------------------------------------------------------------------------

def test_create_page(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Getting Started", "slug": "getting-started", "content": "# Hello"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Getting Started"
    assert data["slug"] == "getting-started"
    assert data["content"] == "# Hello"
    assert data["workspace_id"] == ws["id"]
    assert data["created_by"] == "owner"
    assert data["updated_by"] == "owner"


def test_list_pages_tree(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    parent = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Root", "slug": "root", "content": "root content"},
    ).json()
    child = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Child", "slug": "child", "parent_id": parent["id"], "content": "child content"},
    ).json()

    resp = client.get(f"/workspaces/{ws['id']}/pages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == parent["id"]
    assert data[0]["children"][0]["id"] == child["id"]


def test_get_page(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    page = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "About", "slug": "about", "content": "about content"},
    ).json()

    resp = client.get(f"/workspaces/{ws['id']}/pages/{page['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "About"


def test_update_page(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    page = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Old", "slug": "old", "content": "old content"},
    ).json()

    resp = client.patch(
        f"/workspaces/{ws['id']}/pages/{page['id']}",
        json={"title": "New", "content": "new content"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "New"
    assert data["content"] == "new content"
    assert data["slug"] == "old"


def test_delete_page_by_owner(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    page = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Trash", "slug": "trash", "content": "x"},
    ).json()

    resp = client.delete(f"/workspaces/{ws['id']}/pages/{page['id']}")
    assert resp.status_code == 204
    assert client.get(f"/workspaces/{ws['id']}/pages/{page['id']}").status_code == 404


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_member_can_create_and_update_own_page(client, db_session):
    ws = create_workspace(client, "owner")
    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user", Role.MEMBER.value)
    resp = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Member Page", "slug": "member-page", "content": "hi"},
    )
    assert resp.status_code == 201
    page_id = resp.json()["id"]

    update_resp = client.patch(
        f"/workspaces/{ws['id']}/pages/{page_id}",
        json={"content": "updated by member"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["content"] == "updated by member"


def test_member_cannot_update_others_page(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    page = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Owner Page", "slug": "owner-page", "content": "private"},
    ).json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")
    as_user(client, "member-user", Role.MEMBER.value)
    resp = client.patch(
        f"/workspaces/{ws['id']}/pages/{page['id']}",
        json={"content": "hacked"},
    )
    assert resp.status_code == 403


def test_admin_can_update_and_delete_any_page(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    page = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Admin Target", "slug": "admin-target", "content": "x"},
    ).json()

    add_member(client, db_session, ws["id"], "admin@example.com", Role.ADMIN.value, "admin-user")
    as_user(client, "admin-user", Role.ADMIN.value)
    update_resp = client.patch(
        f"/workspaces/{ws['id']}/pages/{page['id']}",
        json={"content": "admin updated"},
    )
    assert update_resp.status_code == 200
    assert client.delete(f"/workspaces/{ws['id']}/pages/{page['id']}").status_code == 204


def test_guest_cannot_create_page(client, db_session):
    ws = create_workspace(client, "owner")
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user", Role.GUEST.value)
    resp = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Bad", "slug": "bad", "content": "x"},
    )
    assert resp.status_code == 403


def test_guest_cannot_view_pages(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Public", "slug": "public", "content": "x"},
    )
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user", Role.GUEST.value)
    resp = client.get(f"/workspaces/{ws['id']}/pages")
    assert resp.status_code == 403


def test_non_member_cannot_access_pages(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    page = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Secret", "slug": "secret", "content": "x"},
    ).json()

    as_user(client, "stranger", Role.OWNER.value)
    resp = client.get(f"/workspaces/{ws['id']}/pages/{page['id']}")
    assert resp.status_code == 403


def test_cannot_create_duplicate_slug(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "First", "slug": "dup", "content": "x"},
    )
    resp = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Second", "slug": "dup", "content": "y"},
    )
    assert resp.status_code == 409


def test_page_parent_must_be_same_workspace(client, db_session):
    ws = create_workspace(client, "owner")
    other_ws = create_workspace(client, "owner", name="Other", slug="other")
    as_user(client, "owner")
    other_page = client.post(
        f"/workspaces/{other_ws['id']}/pages",
        json={"title": "Other", "slug": "other", "content": "x"},
    ).json()

    resp = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Child", "slug": "child", "parent_id": other_page["id"], "content": "x"},
    )
    assert resp.status_code == 404


def test_search_pages_by_title_and_content(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Getting Started", "slug": "getting-started", "content": "# Hello"},
    )
    client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Deployment", "slug": "deployment", "content": "Deploy to server"},
    )

    resp = client.get(f"/workspaces/{ws['id']}/pages?search=deploy")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Deployment"

    resp = client.get(f"/workspaces/{ws['id']}/pages?search=hello")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Getting Started"

    resp = client.get(f"/workspaces/{ws['id']}/pages?search=")
    assert resp.status_code == 200
    assert resp.json() == []


def test_recent_pages(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    page1 = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "First", "slug": "first", "content": "x"},
    ).json()
    page2 = client.post(
        f"/workspaces/{ws['id']}/pages",
        json={"title": "Second", "slug": "second", "content": "y"},
    ).json()
    # Update first to bump updated_at
    client.patch(f"/workspaces/{ws['id']}/pages/{page1['id']}", json={"content": "updated"})

    resp = client.get(f"/workspaces/{ws['id']}/pages?recent=true&limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == page1["id"]

    resp = client.get(f"/workspaces/{ws['id']}/pages?recent=true")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["id"] == page1["id"]
    assert data[1]["id"] == page2["id"]
