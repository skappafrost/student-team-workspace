"""Tests for the admin audit log endpoint (S07)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app
from models import User, WorkspaceMembership


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_audit.db", echo=False)
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
    # generate some activity
    proj = client.post(f"/workspaces/{wid}/projects", json={"name": "ProjA"}).json()
    client.post(f"/projects/{proj['id']}/tasks", json={"title": "TaskA"})
    client.post(f"/workspaces/{wid}/pages", json={"title": "DocPage", "slug": "docpage"})
    return wid


def test_audit_log_admin_only(client, ws_id):
    as_user(client, "u2", Role.MEMBER.value)
    assert client.get(f"/workspaces/{ws_id}/audit-log").status_code == 403
    as_user(client, "u1")
    res = client.get(f"/workspaces/{ws_id}/audit-log")
    assert res.status_code == 200
    assert len(res.json()) >= 2


def test_audit_log_filters(client, ws_id):
    as_user(client, "u1")
    by_type = client.get(f"/workspaces/{ws_id}/audit-log?target_type=page").json()
    assert all(e["target_type"] == "page" for e in by_type)
    assert len(by_type) >= 1
    by_q = client.get(f"/workspaces/{ws_id}/audit-log?q=DocPage").json()
    assert all("DocPage" in (e["target_label"] or "") for e in by_q)
    empty = client.get(f"/workspaces/{ws_id}/audit-log?verb=no_such_verb").json()
    assert empty == []


def test_audit_log_pagination(client, ws_id):
    as_user(client, "u1")
    page1 = client.get(f"/workspaces/{ws_id}/audit-log?limit=1&offset=0").json()
    page2 = client.get(f"/workspaces/{ws_id}/audit-log?limit=1&offset=1").json()
    assert len(page1) == 1 and len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]
