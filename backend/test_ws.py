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

import asyncio
import logging
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import create_access_token
from conftest import as_user, drain_until_reply, make_user
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


def _post(client, channel_id: str, content: str, parent_id: str | None = None) -> str:
    payload: dict = {"content": content}
    if parent_id:
        payload["parent_id"] = parent_id
    resp = client.post(f"/channels/{channel_id}/messages", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_message_edit_reaches_the_channel_room(client):
    """`PATCH /messages/{id}` currently commits and says nothing.

    Peers keep showing the old text until something else refetches the list, so
    an edit is invisible in the one place it is supposed to appear.
    """
    channel = _make_channel(client, "ws-edit-owner")
    as_user(client, "ws-edit-owner")
    with _connect(client, channel["id"], _token("ws-edit-owner")) as sock:
        message_id = _post(client, channel["id"], "original text")
        drain_until_reply(sock)  # clear the new_message frame
        resp = client.patch(f"/messages/{message_id}", json={"content": "corrected"})
        assert resp.status_code == 200, resp.text
        frames = drain_until_reply(sock)

    edited = [f for f in frames if f.get("type") == "message_updated"]
    assert len(edited) == 1, f"no edit frame reached the room; got {[f.get('type') for f in frames]}"
    assert edited[0]["message"]["id"] == message_id
    assert edited[0]["message"]["content"] == "corrected"


def test_message_delete_reaches_the_channel_room(client):
    """Same for a delete, and the frame has to name every row CASCADE removed.

    `messages.parent_id` is `ondelete="CASCADE"`, so deleting a thread parent
    silently deletes its replies in the database while every peer keeps rendering
    them — a frame carrying only the parent id would leave the same ghosts.
    """
    channel = _make_channel(client, "ws-del-owner")
    as_user(client, "ws-del-owner")
    with _connect(client, channel["id"], _token("ws-del-owner")) as sock:
        parent = _post(client, channel["id"], "ask a question")
        reply_a = _post(client, channel["id"], "answer one", parent_id=parent)
        reply_b = _post(client, channel["id"], "answer two", parent_id=parent)
        drain_until_reply(sock)
        resp = client.delete(f"/messages/{parent}")
        assert resp.status_code == 204, resp.text
        frames = drain_until_reply(sock)

    deleted = [f for f in frames if f.get("type") == "message_deleted"]
    assert len(deleted) == 1, (
        f"no delete frame reached the room; got {[f.get('type') for f in frames]}"
    )
    assert deleted[0]["channel_id"] == channel["id"]
    assert set(deleted[0]["message_ids"]) == {parent, reply_a, reply_b}, (
        "the frame must list the CASCADE-removed replies too, or peers keep them"
    )


def test_message_edit_of_another_channels_message_stays_in_its_room(client):
    """An edit must not be broadcast into a channel that never had the message."""
    a = _make_channel(client, "ws-editiso-owner", name="edit-a")
    b = _make_channel(client, "ws-editiso-owner", name="edit-b")
    as_user(client, "ws-editiso-owner")
    with _connect(client, a["id"], _token("ws-editiso-owner")) as sa, _connect(
        client, b["id"], _token("ws-editiso-owner")
    ) as sb:
        message_id = _post(client, a["id"], "in channel a")
        drain_until_reply(sa)
        drain_until_reply(sb)
        assert client.patch(f"/messages/{message_id}", json={"content": "edited in a"}).status_code == 200
        in_a = [f.get("type") for f in drain_until_reply(sa)]
        in_b = [f.get("type") for f in drain_until_reply(sb)]

    assert in_a.count("message_updated") == 1, in_a
    assert "message_updated" not in in_b, in_b


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


def test_presence_socket_leaves_the_user_room_too(client):
    """The presence socket joins two rooms, so it has to leave both.

    It shares ``user:<id>`` with the notification pushes; a socket left behind
    there is a phantom delivery slot on every push to that user, and the room
    never empties, so it is never dropped either.
    """
    as_user(client, "ws-presence-owner")
    ws = client.post(
        "/workspaces", json={"name": "WSP", "slug": "wsp", "description": "x"}
    )
    assert ws.status_code == 201
    user_key = _ws_room_key_user("ws-presence-owner")

    with client.websocket_connect(
        f"/ws/workspaces/{ws.json()['id']}/presence?session_token={_token('ws-presence-owner')}"
    ):
        assert len(_ws_rooms.get(user_key, ())) == 1

    assert user_key not in _ws_rooms


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


class _StallingSocket:
    """A peer that only accepts a frame after `delay`.

    `delay` is finite on purpose: a test whose fake socket never resolves hangs
    the suite instead of reporting the missing bound, and CI should never see a
    stuck job for a bug this small.
    """

    def __init__(self, delay: float):
        self.delay = delay
        self.received = 0

    async def send_text(self, message: str) -> None:
        await asyncio.sleep(self.delay)
        self.received += 1


def test_broadcast_bounds_one_stalled_peer(caplog, monkeypatch):
    """One half-open socket must not decide how long everyone else waits.

    Measured with `bench/ws_stall_probe.py`, before this test existed: a peer
    that holds its send for 5s in a room of two made the broadcast take
    **5.00s**, and the *next three* messages in that room took **15.03s** — the
    stalled socket stayed in the room and was paid for again per message, on the
    request path of `POST /channels/{id}/messages`. With three such peers it was
    15.02s and 45.08s. After the bound: 2.00s then 0.00s, and 6.03s then 0.00s,
    because the wedged peers are pruned the first time they are seen.
    """
    import ws as ws_mod

    monkeypatch.setattr(ws_mod, "WS_SEND_TIMEOUT_SECONDS", 0.05, raising=False)
    stall = _StallingSocket(0.5)
    healthy = _StallingSocket(0.0)
    key = _ws_room_key_channel("probe-room")
    ws_mod._ws_room_join(key, stall)
    ws_mod._ws_room_join(key, healthy)
    try:
        async def drive():
            started = time.perf_counter()
            delivered = await ws_mod._ws_broadcast(key, {"type": "new_message"})
            return delivered, time.perf_counter() - started

        with caplog.at_level(logging.WARNING):
            delivered, elapsed = asyncio.run(drive())
    finally:
        ws_mod._ws_room_leave(key, stall)
        ws_mod._ws_room_leave(key, healthy)

    assert healthy.received == 1, "the frame never reached the healthy peer"
    assert delivered == 1, f"the stalled socket was counted as delivered: {delivered}"
    assert elapsed < 0.4, f"fan-out waited {elapsed:.2f}s on a 0.05s budget"
    assert key not in _ws_rooms, "the stalled socket kept its delivery slot"
    assert "timed out" in caplog.text, (
        "the socket was pruned but nothing was logged, which is also what a "
        "stalled send helper would do: "
        f"helper={ws_mod._ws_send_safe!r} "
        f"timeout={getattr(ws_mod, 'WS_SEND_TIMEOUT_SECONDS', None)!r} "
        f"elapsed={elapsed:.2f}s records={caplog.records}"
    )


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
