"""TA4-1: Notification fan-out for messages (DMs, @mentions, thread replies).

Message create must notify:
- (a) the DM recipient when the message is sent in a DM channel,
- (b) mentioned users parsed from @display_name tokens (only users
      resolvable as members of the workspace),
- (c) the thread parent author when the message is a reply.

Guarantees: no self-notify, dedupe (a user receiving multiple triggers from
one message is notified exactly once), and unread counters (GET
/notifications?unread_only=true) reflect the new notifications.
"""

import asyncio
import json
from contextlib import contextmanager

from fastapi.testclient import TestClient

from conftest import as_user, auth_headers, make_user
from ws import _ws_room_join, _ws_room_key_user, _ws_room_leave

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_workspace(client: TestClient, db_session) -> dict:
    make_user(db_session, "owner")
    as_user(client, "owner")
    resp = client.post("/workspaces", json={"name": "WS", "slug": "ws", "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _invite_member(client: TestClient, db_session, workspace_id: str, user_id: str, display_name: str | None = None) -> None:
    """Invite + accept a workspace member with the given display name."""
    make_user(db_session, user_id, display_name=display_name or user_id)
    owner_resp = client.post(
        f"/workspaces/{workspace_id}/invites",
        json={"email": f"{user_id}@example.com", "role": "member"},
    )
    assert owner_resp.status_code == 201, owner_resp.text
    token = owner_resp.json()["token"]
    as_user(client, user_id)
    accept = client.post("/invites/accept", json={"token": token})
    assert accept.status_code == 201, accept.text
    as_user(client, "owner")


def _make_channel(client: TestClient, workspace_id: str, name: str = "general", type: str = "general") -> dict:
    resp = client.post(
        f"/workspaces/{workspace_id}/channels",
        json={"name": name, "type": type},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _post_message(client: TestClient, channel_id: str, content: str, parent_id: str | None = None):
    payload: dict = {"content": content}
    if parent_id:
        payload["parent_id"] = parent_id
    return client.post(f"/channels/{channel_id}/messages", json=payload)


def _notifications_for(client: TestClient, user_id: str, unread_only: bool = False) -> list[dict]:
    as_user(client, user_id)
    suffix = "?unread_only=true" if unread_only else ""
    resp = client.get(f"/notifications{suffix}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _dm_between(client: TestClient, workspace_id: str, other_id: str) -> dict:
    resp = client.post(f"/workspaces/{workspace_id}/dms", json={"user_id": other_id})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# (a) DM recipient notification
# ---------------------------------------------------------------------------

def test_dm_message_notifies_recipient(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice")
    dm = _dm_between(client, ws["id"], "alice")

    as_user(client, "owner")
    resp = _post_message(client, dm["id"], "yo alice")
    assert resp.status_code == 201, resp.text

    notes = _notifications_for(client, "alice")
    assert any(n["type"] == "dm" and n["read"] is False for n in notes), notes


def test_dm_message_notifies_only_peer_not_author(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice")
    dm = _dm_between(client, ws["id"], "alice")

    as_user(client, "owner")
    assert _post_message(client, dm["id"], "ping").status_code == 201

    owner_notes = _notifications_for(client, "owner")
    assert not any(n["type"] == "dm" for n in owner_notes), owner_notes


# ---------------------------------------------------------------------------
# (b) @mention notification (workspace members only)
# ---------------------------------------------------------------------------

def test_mention_notifies_member(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice", display_name="Alice")
    _invite_member(client, db_session, ws["id"], "bob", display_name="Bob")
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    resp = _post_message(client, channel["id"], "hey @Alice please review")
    assert resp.status_code == 201, resp.text

    notes = _notifications_for(client, "alice")
    assert any(n["type"] == "mention" for n in notes), notes
    # bob (not mentioned) must not be notified
    bob_notes = _notifications_for(client, "bob")
    assert not any(n["type"] == "mention" for n in bob_notes), bob_notes


def test_mention_requires_workspace_member(client, db_session):
    ws = _setup_workspace(client, db_session)
    # "ghost" exists as a User but is NOT a member of this workspace.
    make_user(db_session, "ghost", display_name="Ghost")
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    resp = _post_message(client, channel["id"], "hey @Ghost are you there")
    assert resp.status_code == 201, resp.text

    notes = _notifications_for(client, "ghost")
    assert not any(n["type"] == "mention" for n in notes), notes


def test_mention_is_case_insensitive(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice", display_name="Alice")
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    resp = _post_message(client, channel["id"], "hey @alice review this")
    assert resp.status_code == 201, resp.text

    notes = _notifications_for(client, "alice")
    assert any(n["type"] == "mention" for n in notes), notes


def test_mention_matches_display_name_not_substring(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice", display_name="Alice")
    _invite_member(client, db_session, ws["id"], "bob", display_name="Alice Bob")
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    # "@Alice Bob" must match the full display name "Alice Bob" (bob), not
    # the prefix "Alice" (alice).
    resp = _post_message(client, channel["id"], "ping @Alice Bob hello")
    assert resp.status_code == 201, resp.text

    alice_notes = _notifications_for(client, "alice")
    bob_notes = _notifications_for(client, "bob")
    assert not any(n["type"] == "mention" for n in alice_notes), alice_notes
    assert any(n["type"] == "mention" for n in bob_notes), bob_notes


# ---------------------------------------------------------------------------
# (c) Thread reply notification
# ---------------------------------------------------------------------------

def test_thread_reply_notifies_parent_author(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice")
    channel = _make_channel(client, ws["id"])

    as_user(client, "alice")
    parent = _post_message(client, channel["id"], "root message").json()

    as_user(client, "owner")
    resp = _post_message(client, channel["id"], "a reply", parent_id=parent["id"])
    assert resp.status_code == 201, resp.text

    notes = _notifications_for(client, "alice")
    assert any(n["type"] == "thread" for n in notes), notes


def test_thread_reply_no_self_notify(client, db_session):
    ws = _setup_workspace(client, db_session)
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    parent = _post_message(client, channel["id"], "root message").json()
    resp = _post_message(client, channel["id"], "self reply", parent_id=parent["id"])
    assert resp.status_code == 201, resp.text

    notes = _notifications_for(client, "owner")
    assert not any(n["type"] == "thread" for n in notes), notes


# ---------------------------------------------------------------------------
# No self-notify in general + dedupe
# ---------------------------------------------------------------------------

def test_no_self_notify_on_own_message(client, db_session):
    ws = _setup_workspace(client, db_session)
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    # Owner mentions themselves: must NOT create a notification for owner.
    resp = _post_message(client, channel["id"], "note to @Owner self")
    assert resp.status_code == 201, resp.text

    notes = _notifications_for(client, "owner")
    assert not any(
        n["type"] in ("mention", "thread", "dm") for n in notes
    ), notes


def test_dedupe_one_notification_per_user_per_message(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice", display_name="Alice")
    channel = _make_channel(client, ws["id"])

    # Alice creates the parent message.
    as_user(client, "alice")
    parent = _post_message(client, channel["id"], "root message").json()

    # Owner replies AND mentions Alice in the same message: exactly ONE
    # notification for Alice.
    as_user(client, "owner")
    resp = _post_message(
        client,
        channel["id"],
        "@Alice replying to your thread",
        parent_id=parent["id"],
    )
    assert resp.status_code == 201, resp.text

    notes = _notifications_for(client, "alice")
    fanout_notes = [n for n in notes if n["type"] in ("mention", "thread", "dm")]
    assert len(fanout_notes) == 1, notes


# ---------------------------------------------------------------------------
# Unread counters
# ---------------------------------------------------------------------------

def test_unread_only_reflects_new_notifications(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice", display_name="Alice")
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    before = _notifications_for(client, "alice", unread_only=True)
    assert before == []

    # _notifications_for re-authenticates the shared client as alice; switch
    # back to owner before posting so the mention comes from a different user.
    as_user(client, "owner")
    resp = _post_message(client, channel["id"], "hello @Alice")
    assert resp.status_code == 201, resp.text

    unread = _notifications_for(client, "alice", unread_only=True)
    assert len(unread) == 1
    assert unread[0]["type"] == "mention"
    assert unread[0]["read"] is False


def test_notification_shape_matches_existing_schema(client, db_session):
    """New notifications must be served through the existing NotificationOut shape."""
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "alice", display_name="Alice")
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    assert _post_message(client, channel["id"], "hi @Alice").status_code == 201

    notes = _notifications_for(client, "alice")
    note = next(n for n in notes if n["type"] == "mention")
    assert set(note.keys()) == {
        "id", "user_id", "type", "title", "content", "link", "read", "created_at",
    }
    assert note["user_id"] == "alice"


# ---------------------------------------------------------------------------
# Activity feed completeness
# ---------------------------------------------------------------------------

def test_message_create_writes_activity(client, db_session):
    ws = _setup_workspace(client, db_session)
    channel = _make_channel(client, ws["id"])

    as_user(client, "owner")
    assert _post_message(client, channel["id"], "hello world").status_code == 201

    as_user(client, "owner")
    resp = client.get(f"/workspaces/{ws['id']}/activity?limit=100")
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert any(
        e["verb"] == "posted in" and e["target_type"] == "channel"
        for e in entries
    ), entries


# ---------------------------------------------------------------------------
# Realtime push (TA4-2): a row that exists is not a frame that arrived
# ---------------------------------------------------------------------------

class _RecordingSocket:
    """Stands in for one of a user's open browser tabs.

    ``TestClient``'s websocket ``receive_json()`` has no timeout, so asking a
    live peer for a frame the server never sent hangs the suite instead of
    failing the test. Joining the real ``user:<id>`` room keeps every step of
    the path that matters — fan-out, ``_ws_notify_user``, room broadcast,
    ``send_text`` — and turns a missing frame into an assertion.
    """

    def __init__(self):
        self.frames: list[dict] = []

    async def send_text(self, message: str) -> None:
        self.frames.append(json.loads(message))


@contextmanager
def _listening_as(user_id: str):
    socket = _RecordingSocket()
    key = _ws_room_key_user(user_id)
    _ws_room_join(key, socket)
    try:
        yield socket
    finally:
        _ws_room_leave(key, socket)


def _pushed_to(socket: _RecordingSocket) -> list[dict]:
    """The ``notification_created`` payloads one socket received."""
    return [
        frame["notification"]
        for frame in socket.frames
        if frame.get("type") == "notification_created"
    ]


def _token_of(user_id: str) -> str:
    return auth_headers(user_id)["Authorization"].removeprefix("Bearer ")


def _drain_until_pong(session) -> list[dict]:
    """Frames received so far, read through a heartbeat barrier.

    ``receive_json()`` has no timeout: a test that reads a fixed number of
    frames hangs forever when the server sends fewer, which is exactly the
    failure mode a missing push has. Both sockets answer a plain-text
    heartbeat with a ``pong``, so the drain is bounded either way.
    """
    session.send_text("ping")
    frames: list[dict] = []
    while True:
        frame = session.receive_json()
        if frame.get("type") == "pong":
            return frames
        frames.append(frame)


def test_channel_socket_receives_the_dm_push(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "member")
    dm = _dm_between(client, ws["id"], "member")

    with client.websocket_connect(
        f"/ws/channels/{dm['id']}?session_token={_token_of('member')}"
    ) as peer:
        as_user(client, "owner")
        assert _post_message(client, dm["id"], "over the wire").status_code == 201
        frames = _drain_until_pong(peer)

    types = [f.get("type") for f in frames]
    assert "new_message" in types, frames
    assert "notification_created" in types, (
        f"a real channel socket saw no notification frame; got {types}"
    )
    pushed = next(f for f in frames if f["type"] == "notification_created")
    assert pushed["notification"]["type"] == "dm", pushed


def test_presence_socket_receives_the_dm_push(client, db_session):
    """A dashboard tab holds a presence socket and no channel socket.

    The push fanned out to the ``user:<id>`` room, which only the channel
    socket joined, so the surface that actually shows the unread badge was the
    one surface that could not hear it.
    """
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "member")
    dm = _dm_between(client, ws["id"], "member")

    with client.websocket_connect(
        f"/ws/workspaces/{ws['id']}/presence?session_token={_token_of('member')}"
    ) as peer:
        # Joining publishes this member's own online frame, broadcast to self.
        assert peer.receive_json()["type"] == "presence_update"
        as_user(client, "owner")
        assert _post_message(client, dm["id"], "on the dashboard").status_code == 201
        frames = _drain_until_pong(peer)

    pushed = [f for f in frames if f.get("type") == "notification_created"]
    assert [p["notification"]["type"] for p in pushed] == ["dm"], (
        f"presence socket saw no push; frames were {[f.get('type') for f in frames]}"
    )


def test_recording_socket_records_a_frame_that_is_actually_sent():
    """Positive control for the harness: an empty list must mean "nothing sent".

    Every push test below asserts that something is missing, so a socket that
    could not record anything at all would make them all pass for the wrong
    reason.
    """
    from ws import _ws_notify_user

    with _listening_as("member") as peer:
        asyncio.run(_ws_notify_user("member", {"id": "n1", "type": "dm"}))

    assert _pushed_to(peer) == [{"id": "n1", "type": "dm"}]


def test_dm_message_pushes_notification_to_peer(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "member")
    dm = _dm_between(client, ws["id"], "member")
    as_user(client, "owner")

    with _listening_as("member") as peer:
        assert _post_message(client, dm["id"], "push me").status_code == 201

    pushed = _pushed_to(peer)
    assert len(pushed) == 1, f"peer received no dm push; frames were: {peer.frames}"
    note = pushed[0]
    assert note["type"] == "dm", note
    assert note["user_id"] == "member", note
    assert note["link"] == f"/dashboard/chat?channel={dm['id']}", note


def test_mention_pushes_notification_to_mentioned_user(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "member", display_name="Member")
    channel = _make_channel(client, ws["id"])
    as_user(client, "owner")

    with _listening_as("member") as mentioned:
        posted = _post_message(client, channel["id"], "hey @member look")
        assert posted.status_code == 201, posted.text

    pushed = _pushed_to(mentioned)
    assert [n["type"] for n in pushed] == ["mention"], (
        f"mentions never reached the push helper; frames were: {mentioned.frames}"
    )


def test_thread_reply_pushes_notification_to_parent_author(client, db_session):
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "member")
    channel = _make_channel(client, ws["id"])
    as_user(client, "member")
    parent = _post_message(client, channel["id"], "top of thread")
    assert parent.status_code == 201, parent.text
    as_user(client, "owner")

    with _listening_as("member") as author:
        reply = _post_message(client, channel["id"], "a reply", parent_id=parent.json()["id"])
        assert reply.status_code == 201, reply.text

    pushed = _pushed_to(author)
    assert [n["type"] for n in pushed] == ["thread"], (
        f"the parent author's socket got no push; frames were: {author.frames}"
    )


def test_push_is_deduped_and_never_sent_to_the_author(client, db_session):
    """One message triggers two rules for the same user; that is one frame."""
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "member", display_name="Member")
    channel = _make_channel(client, ws["id"])
    as_user(client, "member")
    parent = _post_message(client, channel["id"], "parent")
    assert parent.status_code == 201, parent.text
    as_user(client, "owner")

    with _listening_as("member") as peer, _listening_as("owner") as author:
        reply = _post_message(
            client, channel["id"], "reply to you @member", parent_id=parent.json()["id"]
        )
        assert reply.status_code == 201, reply.text

    assert len(_pushed_to(peer)) == 1, peer.frames
    assert _pushed_to(author) == [], "the author was pushed a notification they caused"


def test_pushed_frame_carries_the_row_get_notifications_returns(client, db_session):
    """The frame is a ``NotificationOut``, not a bespoke shape the client must guess."""
    ws = _setup_workspace(client, db_session)
    _invite_member(client, db_session, ws["id"], "member")
    dm = _dm_between(client, ws["id"], "member")
    as_user(client, "owner")

    with _listening_as("member") as peer:
        assert _post_message(client, dm["id"], "canonical shape").status_code == 201

    [pushed] = _pushed_to(peer)
    stored = next(
        n for n in _notifications_for(client, "member") if n["id"] == pushed["id"]
    )
    assert pushed == stored

