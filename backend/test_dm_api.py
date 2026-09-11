"""Tests for direct messages (F05)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app
from models import User


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_dm.db", echo=False)
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


def _add_user(db_session, user_id: str):
    if not db_session.query(User).filter(User.id == user_id).first():
        db_session.add(User(id=user_id, email=f"{user_id}@example.com", display_name=user_id))
        db_session.commit()


def _setup_workspace_with_member(client: TestClient, db_session, member_id: str = "m2"):
    _add_user(db_session, "owner")
    as_user(client, "owner")
    ws = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()

    inv = client.post(
        f"/workspaces/{ws['id']}/invites",
        json={"email": f"{member_id}@example.com", "role": "member"},
    )
    assert inv.status_code == 201, inv.text
    token = inv.json()["token"]
    _add_user(db_session, member_id)
    as_user(client, member_id, Role.MEMBER.value)
    accept = client.post("/invites/accept", json={"token": token})
    assert accept.status_code == 201, accept.text
    as_user(client, "owner")
    return ws


def test_create_dm_returns_channel_with_peer(client, db_session):
    ws = _setup_workspace_with_member(client, db_session)
    resp = client.post(f"/workspaces/{ws['id']}/dms", json={"user_id": "m2"})
    assert resp.status_code == 201, resp.text
    dm = resp.json()
    assert dm["is_private"] is True
    assert dm["type"] == "dm"
    assert dm["peer_id"] == "m2"
    assert dm["peer_name"] == "m2"


def test_create_dm_is_idempotent(client, db_session):
    ws = _setup_workspace_with_member(client, db_session)
    first = client.post(f"/workspaces/{ws['id']}/dms", json={"user_id": "m2"}).json()
    # Other direction returns the same channel.
    as_user(client, "m2", Role.MEMBER.value)
    second = client.post(f"/workspaces/{ws['id']}/dms", json={"user_id": "owner"}).json()
    assert first["id"] == second["id"]
    assert second["peer_id"] == "owner"


def test_dm_self_rejected(client, db_session):
    ws = _setup_workspace_with_member(client, db_session)
    resp = client.post(f"/workspaces/{ws['id']}/dms", json={"user_id": "owner"})
    assert resp.status_code == 400


def test_dm_requires_membership(client, db_session):
    _add_user(db_session, "owner")
    as_user(client, "owner")
    ws = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()

    _add_user(db_session, "outsider")
    as_user(client, "outsider", Role.MEMBER.value)
    resp = client.post(f"/workspaces/{ws['id']}/dms", json={"user_id": "owner"})
    assert resp.status_code == 403


def test_dm_hidden_from_channel_list_and_peer_only_access(client, db_session):
    ws = _setup_workspace_with_member(client, db_session)
    dm = client.post(f"/workspaces/{ws['id']}/dms", json={"user_id": "m2"}).json()

    channels = client.get(f"/workspaces/{ws['id']}/channels").json()
    assert all(c["type"] != "dm" for c in channels)

    # Post a message in the DM, readable by both members.
    msg = client.post(f"/channels/{dm['id']}/messages", json={"content": "secret"})
    assert msg.status_code == 201
    as_user(client, "m2", Role.MEMBER.value)
    msgs = client.get(f"/channels/{dm['id']}/messages")
    assert msgs.status_code == 200
    assert msgs.json()[0]["content"] == "secret"

    # A third workspace member cannot read the DM.
    _add_user(db_session, "third")
    as_user(client, "owner")
    inv = client.post(
        f"/workspaces/{ws['id']}/invites",
        json={"email": "third@example.com", "role": "member"},
    ).json()
    as_user(client, "third", Role.MEMBER.value)
    client.post("/invites/accept", json={"token": inv["token"]})
    resp = client.get(f"/channels/{dm['id']}/messages")
    assert resp.status_code == 403


def test_list_dms_only_own(client, db_session):
    ws = _setup_workspace_with_member(client, db_session)
    client.post(f"/workspaces/{ws['id']}/dms", json={"user_id": "m2"})

    dms = client.get(f"/workspaces/{ws['id']}/dms").json()
    assert len(dms) == 1
    assert dms[0]["peer_id"] == "m2"

    # Third member (not in the DM) sees an empty list.
    _add_user(db_session, "third")
    inv = client.post(
        f"/workspaces/{ws['id']}/invites",
        json={"email": "third@example.com", "role": "member"},
    ).json()
    as_user(client, "third", Role.MEMBER.value)
    client.post("/invites/accept", json={"token": inv["token"]})
    dms = client.get(f"/workspaces/{ws['id']}/dms").json()
    assert dms == []
