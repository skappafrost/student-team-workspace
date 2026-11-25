"""Tests for Channel and Message CRUD endpoints with RBAC."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

import models
from app import Role
from conftest import as_user, clear_auth, make_user

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def create_workspace(client: TestClient, db_session, user_id: str = "owner", name: str = "WS", slug: str = "ws"):
    # Ensure the test user exists with the expected id/display_name.
    make_user(db_session, user_id)
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201
    return resp.json()


def add_member(client, db_session, workspace_id, email, role, user_id):
    """Invite and accept a user into a workspace, return the new membership record."""
    owner_resp = client.post(
        f"/workspaces/{workspace_id}/invites",
        json={"email": email, "role": role},
    )
    assert owner_resp.status_code == 201, owner_resp.text
    token = owner_resp.json()["token"]

    make_user(db_session, user_id, email=email)
    clear_auth(client)
    as_user(client, user_id)
    accept_resp = client.post("/invites/accept", json={"token": token})
    assert accept_resp.status_code == 201, accept_resp.text
    return accept_resp.json()


# ---------------------------------------------------------------------------
# Channel CRUD happy paths
# ---------------------------------------------------------------------------

def test_create_channel(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "general"
    assert data["type"] == "general"
    assert data["workspace_id"] == ws["id"]
    assert data["created_by"] == "owner"


def test_list_channels(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/channels", json={"name": "c1", "type": "general"})
    client.post(f"/workspaces/{ws['id']}/channels", json={"name": "c2", "type": "project"})

    resp = client.get(f"/workspaces/{ws['id']}/channels")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {c["name"] for c in data} == {"c1", "c2"}


# ---------------------------------------------------------------------------
# Message CRUD happy paths
# ---------------------------------------------------------------------------

def test_send_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()

    resp = client.post(f"/channels/{channel['id']}/messages", json={"content": "Hello!"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Hello!"
    assert data["author_id"] == "owner"
    assert data["author_name"] == "owner"
    assert data["channel_id"] == channel["id"]


def test_list_messages(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    client.post(f"/channels/{channel['id']}/messages", json={"content": "first"})
    client.post(f"/channels/{channel['id']}/messages", json={"content": "second"})

    resp = client.get(f"/channels/{channel['id']}/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["content"] == "first"
    assert data[1]["content"] == "second"
    assert all("author_name" in m and m["author_name"] == "owner" for m in data)


def test_update_message_by_owner(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "original"}).json()

    resp = client.patch(f"/messages/{message['id']}", json={"content": "updated"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "updated"


def test_delete_message_by_owner(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "to delete"}).json()

    resp = client.delete(f"/messages/{message['id']}")
    assert resp.status_code == 204
    assert client.get(f"/channels/{channel['id']}/messages").json() == []


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_member_can_create_channel_and_send_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "member-channel", "type": "general"})
    assert resp.status_code == 201
    channel_id = resp.json()["id"]

    resp = client.post(f"/channels/{channel_id}/messages", json={"content": "hi"})
    assert resp.status_code == 201


def test_guest_cannot_create_channel(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "bad", "type": "general"})
    # Guest is a workspace member but lacks write permissions in this implementation
    assert resp.status_code == 403


def test_guest_cannot_send_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user")
    resp = client.post(f"/channels/{channel['id']}/messages", json={"content": "hi"})
    assert resp.status_code == 403


def test_non_member_cannot_list_channels(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"})

    as_user(client, "stranger")
    resp = client.get(f"/workspaces/{ws['id']}/channels")
    assert resp.status_code == 403


def test_member_cannot_update_others_message(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "owner msg"}).json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = client.patch(f"/messages/{message['id']}", json={"content": "hacked"})
    assert resp.status_code == 403


def test_admin_can_moderate_any_message_in_a_public_channel(client, db_session):
    """Admin rank moderates other people's messages where the channel is public.

    The narrow case — a DM or a private channel the admin is not in — is refused,
    and that is pinned in `test_channel_members_api.py`.
    """
    ws = create_workspace(client, db_session, "owner")
    as_user(client, "owner")
    channel = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "general", "type": "general"}).json()
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "owner msg"}).json()

    add_member(client, db_session, ws["id"], "admin@example.com", Role.ADMIN.value, "admin-user")

    as_user(client, "admin-user")
    update_resp = client.patch(f"/messages/{message['id']}", json={"content": "admin updated"})
    assert update_resp.status_code == 200
    assert update_resp.json()["content"] == "admin updated"
    assert client.delete(f"/messages/{message['id']}").status_code == 204


def test_private_channel_requires_admin_to_create(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "private", "type": "private"})
    assert resp.status_code == 403

    as_user(client, "owner")
    resp = client.post(f"/workspaces/{ws['id']}/channels", json={"name": "private", "type": "private"})
    assert resp.status_code == 201
    assert resp.json()["is_private"] is True


# ---------------------------------------------------------------------------
# History windowing: the page a client gets is the tail of the conversation
# ---------------------------------------------------------------------------

BASE = datetime(2026, 1, 1, 12, 0, 0)


def _make_channel(client, ws_id, name="general"):
    as_user(client, "owner")
    resp = client.post(
        f"/workspaces/{ws_id}/channels", json={"name": name, "type": "general"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_messages(db_session, channel_id, count, step_seconds=1, same_second_from=None):
    """Insert messages with explicit timestamps, so ordering is a fact and not a race.

    SQLite's `CURRENT_TIMESTAMP` is second-granular, so rows created in one test
    almost always share a timestamp; seeding the clock is the only way to assert
    which end of the history a page is supposed to return.
    """
    for i in range(count):
        offset = i if same_second_from is None or i < same_second_from else same_second_from
        db_session.add(
            models.Message(
                channel_id=channel_id,
                author_id="owner",
                content=f"m{i}",
                created_at=BASE + timedelta(seconds=offset),
            )
        )
    db_session.commit()


def test_message_list_returns_the_newest_window(client, db_session):
    """`?limit=` must give the tail of the conversation, not its head.

    The query used to order `created_at ASC` and window from offset 0, so the
    first page of a channel was its OLDEST messages and the newest ones were
    absent — invisible in tests, which seed two or three rows and never reach the
    cap, and total in a busy channel.
    """
    ws = create_workspace(client, db_session, "owner")
    ch = _make_channel(client, ws["id"])
    _seed_messages(db_session, ch["id"], 5)

    data = client.get(f"/channels/{ch['id']}/messages", params={"limit": 2}).json()
    assert [m["content"] for m in data] == ["m3", "m4"]


def test_before_walks_back_through_history_without_gaps_or_duplicates(client, db_session):
    """Paging older must terminate on the full history exactly once."""
    ws = create_workspace(client, db_session, "owner")
    ch = _make_channel(client, ws["id"])
    _seed_messages(db_session, ch["id"], 5)

    page1 = client.get(f"/channels/{ch['id']}/messages", params={"limit": 2}).json()
    assert [m["content"] for m in page1] == ["m3", "m4"]

    page2 = client.get(
        f"/channels/{ch['id']}/messages", params={"limit": 2, "before": page1[0]["id"]}
    ).json()
    assert [m["content"] for m in page2] == ["m1", "m2"]

    page3 = client.get(
        f"/channels/{ch['id']}/messages", params={"limit": 2, "before": page2[0]["id"]}
    ).json()
    assert [m["content"] for m in page3] == ["m0"]

    seen = [m["id"] for page in (page1, page2, page3) for m in page]
    assert len(seen) == len(set(seen)) == 5


def test_offset_pages_the_same_history_as_one_full_request(client, db_session):
    """`offset` walks backwards, and the pages stitch into the full list.

    Includes two messages sharing a timestamp: the `id` tie-break exists to keep
    that case stable across separate queries, not to make it chronological. This
    asserts the weaker, checkable property — paging must agree with the
    unpaginated order — which is what makes `offset` honest.
    """
    ws = create_workspace(client, db_session, "owner")
    ch = _make_channel(client, ws["id"])
    _seed_messages(db_session, ch["id"], 4, same_second_from=2)

    full = client.get(f"/channels/{ch['id']}/messages").json()
    assert len(full) == 4

    stitched = []
    for page_index in range(4):
        rows = client.get(
            f"/channels/{ch['id']}/messages", params={"limit": 1, "offset": page_index}
        ).json()
        assert len(rows) == 1
        stitched.extend(rows)

    # Newest-first windows: offset 0 is the last row of the ascending full list.
    assert [m["id"] for m in stitched] == [m["id"] for m in reversed(full)]


def test_rapid_messages_keep_creation_order(client, db_session):
    """Two messages sent in the same second must still come back oldest-first.

    SQLite's `CURRENT_TIMESTAMP` truncates to the second, so a burst of messages
    shared a timestamp and their order was storage-engine luck. That was harmless
    while the list was ordered ASC from row 0, and became a correctness problem the
    moment the window is taken from the newest end: the newest message can land
    *behind* an older one and a backwards page then skips or repeats a row.
    `Message.created_at` now defaults to a naive-UTC microsecond timestamp, so the
    order is the order things happened.
    """
    ws = create_workspace(client, db_session, "owner")
    ch = _make_channel(client, ws["id"])
    as_user(client, "owner")

    ids = []
    for i in range(4):
        created = client.post(
            f"/channels/{ch['id']}/messages", json={"content": f"burst {i}"}
        ).json()
        ids.append(created["id"])

    data = client.get(f"/channels/{ch['id']}/messages").json()
    assert [m["id"] for m in data] == ids

    newest = client.get(f"/channels/{ch['id']}/messages", params={"limit": 1}).json()
    assert [m["id"] for m in newest] == [ids[-1]]


def test_before_rejects_an_unknown_id_and_a_foreign_channel_message(client, db_session):
    """`before` is a client-supplied id, so it is validated like every other one."""
    ws = create_workspace(client, db_session, "owner")
    ch_a = _make_channel(client, ws["id"], name="a")
    ch_b = _make_channel(client, ws["id"], name="b")
    _seed_messages(db_session, ch_b["id"], 1)
    foreign = client.get(f"/channels/{ch_b['id']}/messages").json()[0]

    resp = client.get(
        f"/channels/{ch_a['id']}/messages", params={"before": foreign["id"]}
    )
    assert resp.status_code == 400, resp.text

    assert (
        client.get(
            f"/channels/{ch_a['id']}/messages", params={"before": "no-such-message"}
        ).status_code
        == 404
    )

