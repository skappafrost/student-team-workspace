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

import pytest
from fastapi.testclient import TestClient

from conftest import as_user, make_user


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
