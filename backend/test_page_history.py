"""Tests for wiki page version history (F09)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app
from models import User, WorkspaceMembership


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_page_history.db", echo=False)
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
    db_session.commit()
    as_user(client, "u1")
    return client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()["id"]


def _create_page(client, ws_id, title="Doc", slug="doc", content="v1 text"):
    return client.post(
        f"/workspaces/{ws_id}/pages",
        json={"title": title, "slug": slug, "content": content},
    ).json()


def test_create_records_version_1(client, ws_id):
    as_user(client, "u1")
    page = _create_page(client, ws_id)

    history = client.get(f"/workspaces/{ws_id}/pages/{page['id']}/history").json()
    assert len(history) == 1
    assert history[0]["version"] == 1
    assert history[0]["content"] == "v1 text"
    assert history[0]["author_name"] == "Owner One"


def test_update_appends_versions_newest_first(client, ws_id):
    as_user(client, "u1")
    page = _create_page(client, ws_id)
    client.patch(
        f"/workspaces/{ws_id}/pages/{page['id']}",
        json={"title": "Doc v2", "content": "v2 text"},
    )
    client.patch(
        f"/workspaces/{ws_id}/pages/{page['id']}",
        json={"content": "v3 text"},
    )

    history = client.get(f"/workspaces/{ws_id}/pages/{page['id']}/history").json()
    assert [v["version"] for v in history] == [3, 2, 1]
    assert history[0]["content"] == "v3 text"
    assert history[1]["title"] == "Doc v2"


def test_restore_applies_old_version_as_new_version(client, ws_id):
    as_user(client, "u1")
    page = _create_page(client, ws_id)
    client.patch(
        f"/workspaces/{ws_id}/pages/{page['id']}", json={"content": "v2 text"}
    )

    restored = client.post(
        f"/workspaces/{ws_id}/pages/{page['id']}/restore/1"
    ).json()
    assert restored["content"] == "v1 text"

    history = client.get(f"/workspaces/{ws_id}/pages/{page['id']}/history").json()
    assert history[0]["version"] == 3
    assert history[0]["content"] == "v1 text"


def test_restore_unknown_version_404(client, ws_id):
    as_user(client, "u1")
    page = _create_page(client, ws_id)
    resp = client.post(f"/workspaces/{ws_id}/pages/{page['id']}/restore/99")
    assert resp.status_code == 404
