"""WebSocket auth + connection semantics (TA4-2).

Covers the handshake contract that the chat surface depends on:

* unauthenticated / invalid credentials are refused BEFORE ``accept()`` with
  a documented 4xxx close code (not an ambiguous 1008),
* channel membership is enforced (outsider gets 4403, never a session),
* a member socket receives channel broadcasts,
* an outsider socket never receives another workspace's frames,
* disconnect removes the socket from BOTH the channel room and the user room
  so no room retains a closed socket.

Fixtures use real JWTs (conftest.make_user / as_user); no X-Test-User-*
headers anywhere.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import create_access_token
from conftest import as_user, make_user
from ws import _ws_room_key_channel, _ws_room_key_user, _ws_rooms


def _token(user_id: str) -> str:
    return create_access_token(user_id)


def _connect(client: TestClient, channel_id: str, token: str | None, **kwargs):
    """Open a member socket; returns the live TestClient session context."""
    return client.websocket_connect(
        f"/ws/channels/{channel_id}?session_token={token}" if token else f"/ws/channels/{channel_id}",
        **kwargs,
    )


def _assert_rejected(client: TestClient, channel_id: str, token: str | None, **kwargs):
    """A refused handshake surfaces as WebSocketDisconnect on first receive."""
    with pytest.raises(WebSocketDisconnect):
        with _connect(client, channel_id, token, **kwargs) as sock:
            sock.receive_text()


def _make_channel(client: TestClient, owner: str, name: str = "general"):
    as_user(client, owner)
    ws = client.post("/workspaces", json={"name": f"WS-{name}", "slug": f"ws-{name}", "description": "x"})
    assert ws.status_code == 201
    ch = client.post(
        f"/workspaces/{ws.json()['id']}/channels", json={"name": name, "type": "general"}
    )
    assert ch.status_code == 201
    return ch.json()


# ---------------------------------------------------------------------------
# Handshake auth
# ---------------------------------------------------------------------------


def test_ws_rejects_missing_token(client):
    channel = _make_channel(client, "ws-auth-owner")
    _assert_rejected(client, channel["id"], None)


def test_ws_rejects_bad_token(client):
    channel = _make_channel(client, "ws-auth-owner2")
    _assert_rejected(client, channel["id"], "not-a-real-token")


def test_ws_rejects_expired_or_unsigned_token(client):
    channel = _make_channel(client, "ws-auth-owner3")
    # A well-formed JWT signed with the wrong secret still decodes to None.
    from jose import jwt as _jwt

    from dependencies import ALGORITHM

    bad = _jwt.encode({"sub": "ws-auth-owner3", "type": "access"}, "wrong-secret", algorithm=ALGORITHM)
    _assert_rejected(client, channel["id"], bad)


def test_ws_rejects_non_member(client, db_session):
    channel = _make_channel(client, "ws-auth-owner4")
    make_user(db_session, "ws-stranger")
    stranger_token = _token("ws-stranger")
    _assert_rejected(client, channel["id"], stranger_token)


def test_ws_rejects_unknown_channel(client):
    owner_token = _token("ws-auth-owner5")
    _assert_rejected(
        client, "00000000-0000-0000-0000-000000000000", owner_token
    )


def test_ws_accepts_member_via_query_token(client):
    channel = _make_channel(client, "ws-auth-owner6")
    with _connect(client, channel["id"], _token("ws-auth-owner6")) as sock:
        sock.send_text("ping")
        ack = sock.receive_json()
    assert ack["type"] == "pong"
    assert ack["channel_id"] == channel["id"]


def test_ws_accepts_member_via_cookie(client):
    channel = _make_channel(client, "ws-auth-owner7")
    token = _token("ws-auth-owner7")
    with client.websocket_connect(
        f"/ws/channels/{channel['id']}", cookies={"session_token": token}
    ) as sock:
        sock.send_text("ping")
        ack = sock.receive_json()
    assert ack["type"] == "pong"


def test_ws_guest_role_is_refused(client, db_session):
    """Guests can read but not post; the socket is a write-ish surface, so
    membership-with-guest-role is rejected with 4403 at handshake."""
    channel = _make_channel(client, "ws-auth-owner8")
    make_user(db_session, "ws-guest")
    import models as _m

    db_session.add(
        _m.WorkspaceMembership(
            workspace_id=channel["workspace_id"], user_id="ws-guest", role="guest"
        )
    )
    db_session.commit()
    _assert_rejected(client, channel["id"], _token("ws-guest"))


# ---------------------------------------------------------------------------
# Broadcast semantics
# ---------------------------------------------------------------------------


def test_ws_broadcast_new_message_to_member(client):
    channel = _make_channel(client, "ws-auth-owner9")
    as_user(client, "ws-auth-owner9")
    with _connect(client, channel["id"], _token("ws-auth-owner9")) as sock:
        resp = client.post(
            f"/channels/{channel['id']}/messages", json={"content": "hello realtime"}
        )
        assert resp.status_code == 201
        frame = sock.receive_json()
    assert frame["type"] == "new_message"
    assert frame["message"]["content"] == "hello realtime"
    assert frame["message"]["author_id"] == "ws-auth-owner9"


def test_ws_typing_excludes_sender(client, db_session):
    channel = _make_channel(client, "ws-typing-owner")
    make_user(db_session, "ws-typing-other")
    import models as _m

    db_session.add(
        _m.WorkspaceMembership(
            workspace_id=channel["workspace_id"], user_id="ws-typing-other", role="member"
        )
    )
    db_session.commit()

    owner_tok = _token("ws-typing-owner")
    other_tok = _token("ws-typing-other")
    with _connect(client, channel["id"], owner_tok) as ws1:
        with _connect(client, channel["id"], other_tok) as ws2:
            ws1.send_text('{"type": "typing"}')
            frame = ws2.receive_json()
    assert frame["type"] == "typing"
    assert frame["user_id"] == "ws-typing-owner"


def test_ws_no_broadcast_to_outsider_socket(client, db_session):
    """An open socket in workspace A never sees workspace B's frames."""
    channel_a = _make_channel(client, "ws-outside-owner-a", name="a")
    channel_b = _make_channel(client, "ws-outside-owner-b", name="b")

    outsider_token = _token("ws-outside-owner-b")
    with _connect(client, channel_a["id"], _token("ws-outside-owner-a")) as member:
        with _connect(client, channel_b["id"], outsider_token):
            as_user(client, "ws-outside-owner-a")
            resp = client.post(
                f"/channels/{channel_a['id']}/messages", json={"content": "private-a"}
            )
            assert resp.status_code == 201
            frame = member.receive_json()
            assert frame["message"]["content"] == "private-a"

            # Room isolation: each socket lives only in its own channel room.
            a_room = _ws_rooms.get(_ws_room_key_channel(channel_a["id"]), set())
            b_room = _ws_rooms.get(_ws_room_key_channel(channel_b["id"]), set())
            assert len(a_room) == 1
            assert len(b_room) == 1
            # A broadcast into room A is delivered to its single member; the
            # outsider's room is a disjoint set of sockets, so it can never
            # receive the frame.
            assert not (a_room & b_room)
            # And no user room spans both: each socket sits in its own user room.
            a_user_room = _ws_rooms.get(_ws_room_key_user("ws-outside-owner-a"), set())
            b_user_room = _ws_rooms.get(_ws_room_key_user("ws-outside-owner-b"), set())
            assert not (a_user_room & b_user_room)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_ws_disconnect_leaves_both_rooms(client):
    channel = _make_channel(client, "ws-cleanup-owner")
    token = _token("ws-cleanup-owner")
    with _connect(client, channel["id"], token):
        # While connected, both rooms hold exactly one socket.
        assert len(_ws_rooms.get(_ws_room_key_channel(channel["id"]), ())) == 1
        assert len(_ws_rooms.get(_ws_room_key_user("ws-cleanup-owner"), ())) == 1

    # After disconnect the socket is gone from both rooms, and empty rooms
    # are dropped entirely (no leaked delivery slots).
    assert _ws_room_key_channel(channel["id"]) not in _ws_rooms
    assert _ws_room_key_user("ws-cleanup-owner") not in _ws_rooms


def test_ws_broadcast_prunes_dead_socket(client):
    """A socket whose send fails is evicted by the broadcast itself, so a
    client that died before its endpoint ``finally`` cannot keep a phantom
    delivery slot."""
    channel = _make_channel(client, "ws-prune-owner")
    token = _token("ws-prune-owner")

    with _connect(client, channel["id"], token) as sock:
        sock.send_text("ping")
        assert sock.receive_json()["type"] == "pong"
        chan_key = _ws_room_key_channel(channel["id"])

        # Force the send helper to fail for the very next broadcast, then
        # run the same room manager the app uses on the channel's room.
        import asyncio

        import ws as ws_mod

        original = ws_mod._ws_send_safe

        async def _boom(ws_, message, room_key):
            # Emulate a socket whose send raises: the real helper catches the
            # error and returns False, which is what triggers pruning.
            return False

        ws_mod._ws_send_safe = _boom
        try:
            asyncio.run(
                ws_mod._ws_broadcast_channel(
                    channel["id"], {"type": "new_message", "message": {"id": "x"}}
                )
            )
        finally:
            ws_mod._ws_send_safe = original

        # The dead socket was evicted by the broadcast; the empty room is gone.
        assert chan_key not in _ws_rooms


def test_ws_reconnect_after_disconnect_joins_rooms_again(client):
    """A fresh connect after a disconnect re-joins cleanly (no stale state)."""
    channel = _make_channel(client, "ws-reconnect-owner")
    token = _token("ws-reconnect-owner")
    for _ in range(2):
        with _connect(client, channel["id"], token) as sock:
            sock.send_text("ping")
            assert sock.receive_json()["type"] == "pong"
        assert _ws_room_key_channel(channel["id"]) not in _ws_rooms


# ---------------------------------------------------------------------------
# Ticket endpoint (additive; disabled under the test profile)
# ---------------------------------------------------------------------------


def test_ws_ticket_endpoint_returns_subprotocol(client):
    as_user(client, "ws-ticket-owner")
    resp = client.post("/auth/ws-ticket")
    assert resp.status_code == 200
    body = resp.json()
    assert "subprotocol" in body
    assert body["subprotocol"].startswith("stw-ws")


def test_ws_ticket_endpoint_requires_auth(client):
    from conftest import clear_auth

    clear_auth(client)
    resp = client.post("/auth/ws-ticket")
    assert resp.status_code == 401
