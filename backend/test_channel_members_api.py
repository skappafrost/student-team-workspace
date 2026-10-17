"""Tests for real private-channel membership (T012).

Covers: creator auto-membership, channel_members CRUD endpoints, access
enforcement on list/post messages, WebSocket join, channel listing
visibility, /ai/search and /ai/summarize leakage, and the PATCH
name/topic/type endpoint.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

import models
from app import Base, Role, app
from database import get_db, set_db_url
from models import User

TEST_DB = "sqlite:///./test_stw_channel_members.db"


# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    set_db_url(TEST_DB)
    engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
    # Drop first: a killed previous run can leave this module's file DB with
    # stale rows (create_all alone keeps them → spurious slug conflicts).
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        _restore_suite_db()


@pytest.fixture(scope="function")
def client(db_session):
    set_db_url(TEST_DB)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        _restore_suite_db()


def _restore_suite_db():
    """Point the global engine back at the suite DB.

    This module rebinds the global engine (the WS handler reads the global
    session, not the get_db override), so it must not leak its file DB into
    later test modules (same pollution class as T014 review fixes).

    Restores whatever DATABASE_URL the suite started with (Postgres URL on the
    backend-pg CI job, the sqlite suite file otherwise) so later modules keep
    testing the same dialect instead of leaking this module's file DB.
    """
    from conftest import TEST_DB_PATH
    set_db_url(os.environ.get("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}"))


# ---------------------------------------------------------------------------
# Auth / fixture helpers
# ---------------------------------------------------------------------------

def as_user(client: TestClient, user_id: str, role: str = Role.OWNER.value):
    # Real JWT auth (T004). ``role`` is kept for call-site compatibility but
    # intentionally ignored: the effective role always comes from the DB
    # membership row (helpers above create the right one). User rows are
    # ensured by _ensure_user before every authenticated flow.
    from app import create_access_token
    client.headers["Authorization"] = f"Bearer {create_access_token(user_id)}"
    client.headers.pop("X-Test-User-Id", None)
    client.headers.pop("X-Test-User-Role", None)
    client.cookies.clear()


def clear_auth(client: TestClient):
    client.headers.pop("X-Test-User-Id", None)
    client.headers.pop("X-Test-User-Role", None)
    client.headers.pop("Authorization", None)
    client.cookies.clear()


def _ensure_user(db_session, user_id: str, email: str | None = None):
    existing = db_session.query(User).filter(User.id == user_id).first()
    if not existing:
        user = User(
            id=user_id,
            email=email or f"{user_id}@example.com",
            display_name=user_id,
        )
        db_session.add(user)
        db_session.commit()
    return user_id


def create_workspace(client: TestClient, db_session, user_id: str = "owner",
                     name: str = "WS", slug: str = "ws"):
    _ensure_user(db_session, user_id)
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def add_workspace_member(client, db_session, workspace_id, user_id, role="member", email=None):
    """Invite + accept a user into a workspace; return the membership payload."""
    _ensure_user(db_session, user_id, email)
    email = email or f"{user_id}@example.com"
    as_user(client, "owner")
    invite = client.post(
        f"/workspaces/{workspace_id}/invites",
        json={"email": email, "role": role},
    )
    assert invite.status_code == 201, invite.text
    token = invite.json()["token"]

    clear_auth(client)
    as_user(client, user_id, role)
    accept = client.post("/invites/accept", json={"token": token})
    assert accept.status_code == 201, accept.text
    return accept.json()


def create_private_channel(client, workspace_id, name="private-1", owner="owner"):
    as_user(client, owner)
    resp = client.post(
        f"/workspaces/{workspace_id}/channels",
        json={"name": name, "type": "private"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def create_public_channel(client, workspace_id, name="general", owner="owner"):
    as_user(client, owner)
    resp = client.post(
        f"/workspaces/{workspace_id}/channels",
        json={"name": name, "type": "general"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def post_message(client, channel_id, content, as_user_id="owner", role=Role.OWNER.value):
    as_user(client, as_user_id, role)
    return client.post(f"/channels/{channel_id}/messages", json={"content": content})


def _token_for(user_id: str) -> str:
    from app import create_access_token
    return create_access_token(user_id)


# ---------------------------------------------------------------------------
# Creator auto-membership + listing visibility
# ---------------------------------------------------------------------------

def test_creator_auto_added_on_private_channel_create(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])

    as_user(client, "owner")
    resp = client.get(f"/channels/{channel['id']}/members")
    assert resp.status_code == 200
    members = resp.json()
    assert [m["user_id"] for m in members] == ["owner"]

    # Creator can read messages right away.
    resp = client.get(f"/channels/{channel['id']}/messages")
    assert resp.status_code == 200


def test_private_channel_hidden_from_non_member_channel_list(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    public_ch = create_public_channel(client, ws["id"], "general")
    private_ch = create_private_channel(client, ws["id"], "private-1")
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "alice", Role.MEMBER.value)
    resp = client.get(f"/workspaces/{ws['id']}/channels")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert public_ch["name"] in names
    assert private_ch["name"] not in names

    # Owner (admin) sees everything.
    as_user(client, "owner")
    resp = client.get(f"/workspaces/{ws['id']}/channels")
    names = [c["name"] for c in resp.json()]
    assert private_ch["name"] in names


def test_member_not_in_channel_gets_403_on_messages(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "alice", Role.MEMBER.value)
    resp = client.get(f"/channels/{channel['id']}/messages")
    assert resp.status_code == 403

    resp = client.post(f"/channels/{channel['id']}/messages", json={"content": "hi"})
    assert resp.status_code == 403


def test_member_not_in_channel_cannot_ws_join(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    token = _token_for("alice")
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/channels/{channel['id']}?session_token={token}") as wsock:
            wsock.receive_text()
    # TA4-2: private-channel outsiders are refused at handshake with 4403
    # (the old ambiguous 1008 is still accepted here for back-compat).
    assert exc.value.code in (1008, 4403)


def test_added_member_sees_channel_and_can_interact(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")
    as_user(client, "owner")
    client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"})

    as_user(client, "alice", Role.MEMBER.value)
    # Channel now visible in the list.
    resp = client.get(f"/workspaces/{ws['id']}/channels")
    assert channel["name"] in [c["name"] for c in resp.json()]
    # Can read and write messages.
    assert client.get(f"/channels/{channel['id']}/messages").status_code == 200
    resp = client.post(f"/channels/{channel['id']}/messages", json={"content": "from alice"})
    assert resp.status_code == 201

    # WebSocket join works for a member.
    token = _token_for("alice")
    with client.websocket_connect(f"/ws/channels/{channel['id']}?session_token={token}") as wsock:
        wsock.send_text("ping")
        data = wsock.receive_json()
        assert data["type"] == "pong"


# ---------------------------------------------------------------------------
# Member management endpoints (admin / creator only)
# ---------------------------------------------------------------------------

def test_add_member_requires_admin_or_creator(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")
    add_workspace_member(client, db_session, ws["id"], "bob", role="member")
    add_workspace_member(client, db_session, ws["id"], "admin2", role="admin")

    # Plain member cannot manage members.
    as_user(client, "bob", Role.MEMBER.value)
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"})
    assert resp.status_code == 403

    # Creator can.
    as_user(client, "owner")
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"})
    assert resp.status_code == 201
    assert resp.json()["user_id"] == "alice"
    assert resp.json()["display_name"] == "alice"

    # Admin (non-creator) can.
    as_user(client, "admin2", Role.ADMIN.value)
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "bob"})
    assert resp.status_code == 201

    # Non-admin cannot remove either.
    as_user(client, "bob", Role.MEMBER.value)
    resp = client.delete(f"/channels/{channel['id']}/members/alice")
    assert resp.status_code == 403


def test_add_member_to_public_channel_rejected(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_public_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "owner")
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"})
    assert resp.status_code == 400

    resp = client.delete(f"/channels/{channel['id']}/members/alice")
    assert resp.status_code == 400


def test_add_member_must_be_workspace_member(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    _ensure_user(db_session, "outsider")

    as_user(client, "owner")
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "outsider"})
    assert resp.status_code == 403  # workspace member check

    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "ghost-user"})
    assert resp.status_code == 404  # no such user


def test_duplicate_add_returns_409(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "owner")
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"})
    assert resp.status_code == 201
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"})
    assert resp.status_code == 409


def test_remove_member_revokes_access(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")
    as_user(client, "owner")
    assert client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"}).status_code == 201

    resp = client.delete(f"/channels/{channel['id']}/members/alice")
    assert resp.status_code == 204

    as_user(client, "alice", Role.MEMBER.value)
    assert client.get(f"/channels/{channel['id']}/messages").status_code == 403


def test_remove_creator_membership_keeps_channel_alive(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "admin2", role="admin")

    # Deleting the creator's membership row does not delete the channel and
    # the creator keeps access via the created_by rule.
    as_user(client, "owner")
    resp = client.delete(f"/channels/{channel['id']}/members/owner")
    assert resp.status_code == 204

    as_user(client, "owner")
    assert client.get(f"/channels/{channel['id']}/messages").status_code == 200

    # Admin can still manage the channel afterwards.
    as_user(client, "admin2", Role.ADMIN.value)
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "owner"})
    assert resp.status_code == 201


def test_list_members_requires_channel_access(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "alice", Role.MEMBER.value)
    resp = client.get(f"/channels/{channel['id']}/members")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /channels/{id}
# ---------------------------------------------------------------------------

def test_patch_channel_name_and_topic(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])

    as_user(client, "owner")
    resp = client.patch(f"/channels/{channel['id']}", json={"name": "renamed", "topic": "hello"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"


def test_patch_channel_requires_manager(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "alice", Role.MEMBER.value)
    resp = client.patch(f"/channels/{channel['id']}", json={"name": "hijack"})
    assert resp.status_code == 403


def test_patch_public_to_private_adds_creator_membership(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_public_channel(client, ws["id"], "general")

    as_user(client, "owner")
    resp = client.patch(f"/channels/{channel['id']}", json={"type": "private"})
    assert resp.status_code == 200
    assert resp.json()["is_private"] is True

    members = client.get(f"/channels/{channel['id']}/members").json()
    assert "owner" in [m["user_id"] for m in members]


def test_patch_private_by_member_creator_requires_admin(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    create_public_channel(client, ws["id"], "general")

    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/channels", json={"name": "x", "type": "general"})
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    # alice creates a public channel, then tries to make it private -> 403.
    as_user(client, "alice", Role.MEMBER.value)
    resp = client.post(
        f"/workspaces/{ws['id']}/channels",
        json={"name": "alice-ch", "type": "general"},
    )
    assert resp.status_code == 201
    alice_ch = resp.json()

    resp = client.patch(f"/channels/{alice_ch['id']}", json={"type": "private"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# AI surfaces must respect private-channel membership
# ---------------------------------------------------------------------------

def test_ai_search_excludes_private_channel_messages_for_non_members(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"], "confidential")
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "owner")
    post_message(client, channel["id"], "confidential-berry launch date is 42", as_user_id="owner")

    # Non-member workspace user: no message results leak.
    as_user(client, "alice", Role.MEMBER.value)
    resp = client.get("/ai/search", params={"q": "confidential", "scope": "messages"})
    assert resp.status_code == 200
    message_hits = [r for r in resp.json()["results"] if r["kind"] == "message"]
    assert message_hits == []

    # Admin still finds it.
    as_user(client, "owner")
    resp = client.get("/ai/search", params={"q": "confidential", "scope": "messages"})
    message_hits = [r for r in resp.json()["results"] if r["kind"] == "message"]
    assert len(message_hits) == 1

    # Once added, the member finds it too.
    as_user(client, "owner")
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"})
    assert resp.status_code == 201
    as_user(client, "alice", Role.MEMBER.value)
    resp = client.get("/ai/search", params={"q": "confidential", "scope": "messages"})
    message_hits = [r for r in resp.json()["results"] if r["kind"] == "message"]
    assert len(message_hits) == 1


def test_ai_search_public_channel_messages_visible_to_all_members(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_public_channel(client, ws["id"], "general")
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "owner")
    post_message(client, channel["id"], "standup notes for everyone", as_user_id="owner")

    as_user(client, "alice", Role.MEMBER.value)
    resp = client.get("/ai/search", params={"q": "standup", "scope": "messages"})
    message_hits = [r for r in resp.json()["results"] if r["kind"] == "message"]
    assert len(message_hits) == 1


def test_summarize_channel_gated_for_non_member(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "alice", Role.MEMBER.value)
    resp = client.post("/ai/summarize", json={"kind": "channel", "ref_id": channel["id"]})
    assert resp.status_code == 403

    as_user(client, "owner")
    resp = client.post("/ai/summarize", json={"kind": "channel", "ref_id": channel["id"]})
    assert resp.status_code == 200
    assert "summary" in resp.json()


# ---------------------------------------------------------------------------
# Public channel access regression
# ---------------------------------------------------------------------------

def test_public_channel_accessible_to_all_workspace_members(client, db_session):
    ws = create_workspace(client, db_session, "owner")
    channel = create_public_channel(client, ws["id"], "general")
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")

    as_user(client, "alice", Role.MEMBER.value)
    assert client.get(f"/channels/{channel['id']}/messages").status_code == 200
    assert client.post(f"/channels/{channel['id']}/messages", json={"content": "hi"}).status_code == 201


# ---------------------------------------------------------------------------
# SEC-07 — a workspace admin does not outrank a direct message
# ---------------------------------------------------------------------------


def _dm(client, db_session, ws_id, a="alice", b="bob"):
    add_workspace_member(client, db_session, ws_id, a, role="member")
    add_workspace_member(client, db_session, ws_id, b, role="member")
    as_user(client, a, Role.MEMBER.value)
    resp = client.post(f"/workspaces/{ws_id}/dms", json={"user_id": b})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_admin_cannot_enroll_themselves_in_someone_elses_dm(client, db_session):
    """`_require_channel_manager` used to treat any admin as manager of any channel.

    The read gate (`_is_private_channel_member`) has no admin bypass, so the
    whole exposure came from the enrollment path: enroll, then read.
    """
    ws = create_workspace(client, db_session, "owner")
    dm = _dm(client, db_session, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "admin2", role="admin")

    as_user(client, "admin2", Role.ADMIN.value)
    resp = client.post(f"/channels/{dm['id']}/members", json={"user_id": "admin2"})
    assert resp.status_code == 403, resp.text

    # Refused means no access, not just no write: the DM's messages stay closed.
    resp = client.get(f"/channels/{dm['id']}/messages")
    assert resp.status_code == 403, resp.text


def test_admin_cannot_remove_a_participant_from_a_dm(client, db_session):
    """Neither half of the manager power reaches into a DM."""
    ws = create_workspace(client, db_session, "owner")
    dm = _dm(client, db_session, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "admin2", role="admin")

    as_user(client, "admin2", Role.ADMIN.value)
    resp = client.delete(f"/channels/{dm['id']}/members/bob")
    assert resp.status_code == 403, resp.text

    as_user(client, "bob", Role.MEMBER.value)
    assert client.get(f"/channels/{dm['id']}/messages").status_code == 200


def test_dm_participants_still_manage_their_own_dm(client, db_session):
    """Positive control: the exemption is about admins, not a freeze on DMs."""
    ws = create_workspace(client, db_session, "owner")
    dm = _dm(client, db_session, ws["id"])

    as_user(client, "alice", Role.MEMBER.value)
    resp = client.delete(f"/channels/{dm['id']}/members/bob")
    assert resp.status_code == 204, resp.text


def test_admin_membership_change_on_a_private_channel_is_audited(client, db_session):
    """Admin power over private *team* channels stays (docs/API.md says so) — but it leaves a trace."""
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"], name="team-private")
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")
    add_workspace_member(client, db_session, ws["id"], "admin2", role="admin")

    as_user(client, "admin2", Role.ADMIN.value)
    resp = client.post(f"/channels/{channel['id']}/members", json={"user_id": "alice"})
    assert resp.status_code == 201, resp.text

    rows = (
        db_session.query(models.Activity)
        .filter(models.Activity.workspace_id == ws["id"])
        .all()
    )
    entries = [a for a in rows if a.actor_id == "admin2" and a.target_id == channel["id"]]
    assert entries, (
        "an admin changed channel membership with nothing recorded: "
        f"{[(a.actor_id, a.verb, a.target_type, a.target_id) for a in rows]}"
    )


# ---------------------------------------------------------------------------
# Message moderation follows channel access, not workspace rank
# ---------------------------------------------------------------------------


def create_dm(client, workspace_id, peer, creator="owner"):
    as_user(client, creator)
    resp = client.post(f"/workspaces/{workspace_id}/dms", json={"user_id": peer})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_admin_outsider_cannot_edit_or_delete_a_dm_message(client, db_session):
    """Rank must not reach into someone else's 1:1 conversation.

    The read gate has never allowed it, so the same caller used to answer `403`
    on `GET /channels/{dm}/messages` and `200` on `PATCH /messages/{id}` for a
    message inside that very DM.
    """
    ws = create_workspace(client, db_session, "owner")
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")
    add_workspace_member(client, db_session, ws["id"], "admin2", role="admin")

    dm = create_dm(client, ws["id"], peer="alice", creator="owner")
    msg = post_message(client, dm["id"], "private to alice and owner", as_user_id="alice")
    assert msg.status_code == 201, msg.text
    message = msg.json()

    as_user(client, "admin2", Role.ADMIN.value)
    edit = client.patch(f"/messages/{message['id']}", json={"content": "tampered"})
    delete = client.delete(f"/messages/{message['id']}")
    assert edit.status_code == 403, edit.text
    assert delete.status_code == 403, delete.text

    # And the message is actually untouched, not merely refused on the way out.
    as_user(client, "alice", Role.MEMBER.value)
    listed = client.get(f"/channels/{dm['id']}/messages").json()
    assert [m["content"] for m in listed] == ["private to alice and owner"]


def test_admin_outsider_cannot_moderate_a_private_team_channel_message(client, db_session):
    """The same rule covers private team channels: no channel access, no moderation."""
    ws = create_workspace(client, db_session, "owner")
    channel = create_private_channel(client, ws["id"], name="team-private")
    add_workspace_member(client, db_session, ws["id"], "admin2", role="admin")

    msg = post_message(client, channel["id"], "team-private content")
    assert msg.status_code == 201, msg.text

    as_user(client, "admin2", Role.ADMIN.value)
    assert client.patch(f"/messages/{msg.json()['id']}", json={"content": "x"}).status_code == 403
    assert client.delete(f"/messages/{msg.json()['id']}").status_code == 403


def test_author_still_edits_own_message_inside_a_dm(client, db_session):
    """Participants keep control of their own words — this is a scope change, not a lockout."""
    ws = create_workspace(client, db_session, "owner")
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")
    dm = create_dm(client, ws["id"], peer="alice", creator="owner")

    msg = post_message(client, dm["id"], "first draft", as_user_id="alice")
    message = msg.json()

    as_user(client, "alice", Role.MEMBER.value)
    edit = client.patch(f"/messages/{message['id']}", json={"content": "second draft"})
    assert edit.status_code == 200, edit.text
    assert client.delete(f"/messages/{message['id']}").status_code == 204


def test_admin_moderation_in_a_public_channel_still_works_and_is_audited(client, db_session):
    """Public channels keep the documented admin power, and rank-based edits leave a trace."""
    ws = create_workspace(client, db_session, "owner")
    channel = create_public_channel(client, ws["id"])
    add_workspace_member(client, db_session, ws["id"], "alice", role="member")
    add_workspace_member(client, db_session, ws["id"], "admin2", role="admin")

    msg = post_message(client, channel["id"], "alice says", as_user_id="alice")
    message = msg.json()

    as_user(client, "admin2", Role.ADMIN.value)
    edit = client.patch(f"/messages/{message['id']}", json={"content": "admin says"})
    assert edit.status_code == 200, edit.text
    assert client.delete(f"/messages/{message['id']}").status_code == 204

    rows = (
        db_session.query(models.Activity)
        .filter(models.Activity.workspace_id == ws["id"])
        .all()
    )
    moderation = [a for a in rows if a.actor_id == "admin2" and a.target_id == channel["id"]]
    assert [a.verb for a in moderation] == ["edited message in", "deleted message in"], [
        (a.actor_id, a.verb, a.target_type) for a in rows
    ]
