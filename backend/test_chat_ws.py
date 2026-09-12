"""Tests for WebSocket realtime message broadcast."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from app import Base, app
from database import get_db, set_db_url


def _token_for(user_id: str) -> str:
    from app import create_access_token

    return create_access_token(user_id)


@pytest.fixture(scope="function")
def db_session():
    url = "sqlite:///./test_stw_ws.db"
    set_db_url(url)
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        # Restore the module-level engine — S02's revocation check reads it.
        from config import settings

        set_db_url(settings.database_url)


@pytest.fixture(scope="function")
def client(db_session):
    set_db_url("sqlite:///./test_stw_ws.db")
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(client: TestClient, user_id: str, role: str = "owner"):
    client.headers["X-Test-User-Id"] = user_id
    client.headers["X-Test-User-Role"] = role


def create_workspace(
    client: TestClient, user_id: str = "owner", name: str = "WS", slug: str = "ws"
):
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201
    return resp.json()


def _ws_connect(path: str):
    return pytest.raises(WebSocketDisconnect)


def test_ws_rejects_missing_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/channels/123") as wsock:
            wsock.receive_text()


def test_ws_rejects_bad_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/channels/123?session_token=bad-token") as wsock:
            wsock.receive_text()


def test_ws_broadcast_new_message(client):
    ws_owner = "owner-ws"
    ws = create_workspace(client, ws_owner)
    as_user(client, ws_owner)
    channel = client.post(
        f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}
    ).json()
    channel_id = channel["id"]

    token = _token_for(ws_owner)

    with client.websocket_connect(f"/ws/channels/{channel_id}?session_token={token}") as wsock:
        as_user(client, ws_owner)
        resp = client.post(f"/channels/{channel_id}/messages", json={"content": "hello realtime"})
        assert resp.status_code == 201

        data = wsock.receive_json()
        assert data["type"] == "new_message"
        assert data["message"]["content"] == "hello realtime"
        assert data["message"]["author_id"] == ws_owner


def test_ws_rejects_non_member(client):
    ws_owner = "owner-ws2"
    ws = create_workspace(client, ws_owner)
    as_user(client, ws_owner)
    channel = client.post(
        f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}
    ).json()

    stranger_token = _token_for("stranger")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/channels/{channel['id']}?session_token={stranger_token}"
        ) as wsock:
            wsock.receive_text()


def test_ws_typing_broadcast_excludes_sender(client, db_session):
    ws_owner = "owner-typing"
    ws = create_workspace(client, ws_owner, name="WS-T", slug="ws-t")
    as_user(client, ws_owner)
    channel = client.post(
        f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}
    ).json()
    channel_id = channel["id"]

    token = _token_for(ws_owner)
    other = _token_for("other-user")
    # other must be a member
    import models as _m
    db_session.add(
        _m.WorkspaceMembership(workspace_id=ws["id"], user_id="other-user", role="member")
    )
    db_session.commit()

    with client.websocket_connect(f"/ws/channels/{channel_id}?session_token={token}") as ws1:
        with client.websocket_connect(
            f"/ws/channels/{channel_id}?session_token={other}"
        ) as ws2:
            ws1.send_text('{"type": "typing"}')
            data = ws2.receive_json()
            assert data["type"] == "typing"
            assert data["user_id"] == ws_owner
            assert data["channel_id"] == channel_id
