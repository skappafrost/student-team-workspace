"""Tests for wiki backlinks (F10)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app, create_access_token
from models import User


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_backlinks.db", echo=False)
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
    _client = TestClient(app)
    _client._db = db_session  # lets as_user() ensure the User row exists
    yield _client
    app.dependency_overrides.clear()


def as_user(client: TestClient, user_id: str, role: str = Role.OWNER.value):
    # Real JWT auth (post-T004): mint a real token; the role arg is legacy —
    # workspace roles come from membership rows, not headers.
    db = getattr(client, "_db", None)
    if db is not None and not db.query(User).filter(User.id == user_id).first():
        db.add(User(id=user_id, email=f"{user_id}@example.com", display_name=user_id))
        db.commit()
    client.headers["Authorization"] = f"Bearer {create_access_token(user_id)}"


@pytest.fixture(scope="function")
def ws_id(client, db_session):
    db_session.add(User(id="u1", email="u1@example.com", display_name="Owner One"))
    db_session.commit()
    as_user(client, "u1")
    return client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()["id"]


def _mk(client, ws_id, title, slug, content=""):
    return client.post(
        f"/workspaces/{ws_id}/pages",
        json={"title": title, "slug": slug, "content": content},
    ).json()


def test_backlinks_match_title_and_slug(client, ws_id):
    as_user(client, "u1")
    target = _mk(client, ws_id, "Meeting Notes", "meeting-notes")
    _mk(client, ws_id, "A", "a", "See [[Meeting Notes]] for details.")
    _mk(client, ws_id, "B", "b", "Linked via [[meeting-notes]].")
    _mk(client, ws_id, "C", "c", "No link here.")

    resp = client.get(f"/workspaces/{ws_id}/pages/{target['id']}/backlinks")
    assert resp.status_code == 200
    titles = {p["title"] for p in resp.json()}
    assert titles == {"A", "B"}


def test_backlinks_exclude_self_and_other_workspace(client, ws_id):
    as_user(client, "u1")
    target = _mk(client, ws_id, "Target", "target", "I link [[Target]] myself.")
    other_ws = client.post("/workspaces", json={"name": "WS2", "slug": "ws2"}).json()
    _mk(client, other_ws["id"], "X", "x", "[[Target]]")

    links = client.get(f"/workspaces/{ws_id}/pages/{target['id']}/backlinks").json()
    assert links == []
