"""Tests for message reactions (F04)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app
from models import User


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_reactions.db", echo=False)
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


def _setup_message(client: TestClient, db_session, user_id: str = "owner"):
    """Create user + workspace + channel + message, return (channel, message)."""
    if not db_session.query(User).filter(User.id == user_id).first():
        db_session.add(
            User(id=user_id, email=f"{user_id}@example.com", display_name=user_id)
        )
        db_session.commit()
    as_user(client, user_id)
    ws = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()
    channel = client.post(
        f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}
    ).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "hi"}).json()
    return channel, message


def test_toggle_reaction_add_and_remove(client, db_session):
    channel, message = _setup_message(client, db_session)

    resp = client.post(f"/messages/{message['id']}/reactions", json={"emoji": "👍"})
    assert resp.status_code == 200
    summary = resp.json()
    assert summary == [{"emoji": "👍", "count": 1, "user_ids": ["owner"]}]

    # Toggle again removes it.
    resp = client.post(f"/messages/{message['id']}/reactions", json={"emoji": "👍"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_reactions_appear_in_message_list(client, db_session):
    channel, message = _setup_message(client, db_session)
    client.post(f"/messages/{message['id']}/reactions", json={"emoji": "🎉"})

    messages = client.get(f"/channels/{channel['id']}/messages").json()
    assert len(messages) == 1
    assert messages[0]["reactions"] == [{"emoji": "🎉", "count": 1, "user_ids": ["owner"]}]


def test_two_users_same_emoji_grouped(client, db_session):
    channel, message = _setup_message(client, db_session)
    # Second user joins workspace.
    ws_id = client.get("/workspaces").json()[0]["id"]
    inv = client.post(
        f"/workspaces/{ws_id}/invites", json={"email": "m2@example.com", "role": "member"}
    )
    assert inv.status_code == 201, inv.text
    token = inv.json()["token"]
    if not db_session.query(User).filter(User.id == "m2").first():
        db_session.add(User(id="m2", email="m2@example.com", display_name="m2"))
        db_session.commit()

    client.post(f"/messages/{message['id']}/reactions", json={"emoji": "❤️"})
    as_user(client, "m2", Role.MEMBER.value)
    accept = client.post("/invites/accept", json={"token": token})
    assert accept.status_code == 201, accept.text
    resp = client.post(f"/messages/{message['id']}/reactions", json={"emoji": "❤️"})
    assert resp.status_code == 200
    summary = resp.json()
    assert summary[0]["emoji"] == "❤️"
    assert summary[0]["count"] == 2
    assert set(summary[0]["user_ids"]) == {"owner", "m2"}

    # m2 removes own reaction; owner's remains.
    resp = client.post(f"/messages/{message['id']}/reactions", json={"emoji": "❤️"})
    assert resp.json() == [{"emoji": "❤️", "count": 1, "user_ids": ["owner"]}]


def test_reaction_requires_workspace_membership(client, db_session):
    channel, message = _setup_message(client, db_session)
    db_session.add(
        User(id="outsider", email="o@example.com", display_name="o")
    )
    db_session.commit()
    as_user(client, "outsider", Role.MEMBER.value)
    resp = client.post(f"/messages/{message['id']}/reactions", json={"emoji": "👍"})
    assert resp.status_code == 403


def test_reaction_on_missing_message_404(client, db_session):
    _setup_message(client, db_session)
    resp = client.post("/messages/does-not-exist/reactions", json={"emoji": "👍"})
    assert resp.status_code == 404


def test_reaction_emoji_validation(client, db_session):
    channel, message = _setup_message(client, db_session)
    resp = client.post(f"/messages/{message['id']}/reactions", json={"emoji": ""})
    assert resp.status_code == 422
    resp = client.post(f"/messages/{message['id']}/reactions", json={"emoji": "x" * 40})
    assert resp.status_code == 422


def test_message_search_filters_by_content(client, db_session):
    channel, _ = _setup_message(client, db_session)
    client.post(f"/channels/{channel['id']}/messages", json={"content": "deploy the slides"})
    client.post(f"/channels/{channel['id']}/messages", json={"content": "lunch at noon"})

    all_msgs = client.get(f"/channels/{channel['id']}/messages").json()
    assert len(all_msgs) == 3

    hits = client.get(f"/channels/{channel['id']}/messages", params={"q": "slides"}).json()
    assert [m["content"] for m in hits] == ["deploy the slides"]

    # Case-insensitive.
    hits = client.get(f"/channels/{channel['id']}/messages", params={"q": "LUNCH"}).json()
    assert [m["content"] for m in hits] == ["lunch at noon"]

    # No match -> empty, not error.
    hits = client.get(f"/channels/{channel['id']}/messages", params={"q": "zzz"}).json()
    assert hits == []
