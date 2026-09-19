"""Tests for WebSocket realtime message broadcast."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conftest import as_user


def _token_for(user_id: str) -> str:
    from app import create_access_token
    return create_access_token(user_id)


def create_workspace(client: TestClient, user_id: str = "owner", name: str = "WS", slug: str = "ws"):
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
        f"/workspaces/{ws['id']}/channels",
        json={"name": "general", "type": "general"}
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
        f"/workspaces/{ws['id']}/channels",
        json={"name": "general", "type": "general"}
    ).json()

    stranger_token = _token_for("stranger")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/channels/{channel['id']}?session_token={stranger_token}") as wsock:
            wsock.receive_text()


def test_ws_typing_broadcast_excludes_sender(client, db_session):
    """F11: a typing frame from one socket reaches other members, not the sender."""
    ws_owner = "owner-typing"
    ws = create_workspace(client, ws_owner, name="WS-T", slug="ws-t")
    as_user(client, ws_owner)
    channel = client.post(
        f"/workspaces/{ws['id']}/channels",
        json={"name": "general", "type": "general"}
    ).json()
    channel_id = channel["id"]

    import models as _m
    from conftest import make_user

    make_user(db_session, "other-user")
    db_session.add(
        _m.WorkspaceMembership(workspace_id=ws["id"], user_id="other-user", role="member")
    )
    db_session.commit()

    token = _token_for(ws_owner)
    other = _token_for("other-user")

    with client.websocket_connect(f"/ws/channels/{channel_id}?session_token={token}") as ws1:
        with client.websocket_connect(
            f"/ws/channels/{channel_id}?session_token={other}"
        ) as ws2:
            ws1.send_text('{"type": "typing"}')
            data = ws2.receive_json()
            assert data["type"] == "typing"
            assert data["user_id"] == ws_owner
            assert data["channel_id"] == channel_id
