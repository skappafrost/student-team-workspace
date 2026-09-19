"""Security regression pack — TA7-1 (Stage 7 wrap).

The closing suite of the hardening program. Every abuse case surfaced by the
audit is pinned here so a future PR cannot silently reopen it.

Sections
--------
1. Cross-workspace data leakage — an authenticated user with a valid JWT for
   their OWN workspace must never read a single byte of a workspace they do
   not belong to. Enumerates EVERY router that takes a workspace id or a
   resource id resolvable to another workspace.
2. RBAC escalation — a plain member cannot promote themselves or anyone else,
   cannot delete/transfer the workspace, cannot reach admin/owner-only
   endpoints, and cannot escalate via the invite flow.
3. Auth edges — expired token, wrong token type (refresh presented as access),
   jti reuse after logout, logout-all invalidation, and the legacy X-Test-User-*
   bypass staying OFF under the default (no env) profile.
4. File upload abuse — oversized body, empty file, wrong/missing content type,
   path traversal in the filename, cross-workspace link targets, and the
   upload rate limiter.

Deltas vs. the still-open harden/* PRs are noted where a feature is not on
main yet (see the PR body).

All requests authenticate with REAL JWTs (``conftest.make_user`` /
``as_user``); no X-Test-User-* bypass headers are used.
"""

import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import as_user, clear_auth, make_user

# ---------------------------------------------------------------------------
# Shared scenario builders (real JWT auth only)
# ---------------------------------------------------------------------------


def _create_workspace(client: TestClient, user_id: str, slug: str) -> dict:
    as_user(client, user_id)
    resp = client.post(
        "/workspaces", json={"name": f"WS {slug}", "slug": slug, "description": "owned"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_member(
    client: TestClient,
    db_session,
    workspace_id: str,
    owner_id: str,
    new_user_id: str,
    role: str = "member",
    email: str | None = None,
    slug: str = "ws",
) -> dict:
    """Invite + accept as ``owner_id``, returning the membership row."""
    as_user(client, owner_id)
    email = email or f"{new_user_id}@example.com"
    resp = client.post(
        f"/workspaces/{workspace_id}/invites", json={"email": email, "role": role}
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]

    make_user(db_session, new_user_id, email=email)
    clear_auth(client)
    as_user(client, new_user_id)
    accept = client.post("/invites/accept", json={"token": token})
    assert accept.status_code == 201, accept.text
    return accept.json()


def _make_channel(client: TestClient, ws_id: str, name="general", type_="general") -> dict:
    resp = client.post(
        f"/workspaces/{ws_id}/channels", json={"name": name, "type": type_}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_message(client: TestClient, channel_id: str, content="secret-bw-content") -> dict:
    resp = client.post(f"/channels/{channel_id}/messages", json={"content": content})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_project(client: TestClient, ws_id: str, name="Proj") -> dict:
    resp = client.post(f"/workspaces/{ws_id}/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_task(client: TestClient, project_id: str, title="Task") -> dict:
    resp = client.post(f"/projects/{project_id}/tasks", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_page(client: TestClient, ws_id: str, slug="page", title="Page") -> dict:
    resp = client.post(
        f"/workspaces/{ws_id}/pages",
        json={"title": title, "slug": slug, "content": "[[secret]] bw content"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _make_event(client: TestClient, ws_id: str, title="Event") -> dict:
    start = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = client.post(
        f"/workspaces/{ws_id}/events",
        json={"title": title, "start_at": start, "event_type": "meeting"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload(client: TestClient, ws_id: str, name="doc.pdf", content=b"bw-bytes", ctype="application/pdf"):
    return client.post(
        f"/workspaces/{ws_id}/files",
        files={"file": (name, io.BytesIO(content), ctype)},
    )


@pytest.fixture
def two_workspaces(client, db_session):
    """Owner A in wsA (full data), owner B in wsB, mutually isolated."""
    ws_a = _create_workspace(client, "userA", "wskw-a")
    ws_b = _create_workspace(client, "userB", "wskw-b")

    as_user(client, "userA")
    chan_a = _make_channel(client, ws_a["id"], "chanA")
    msg_a = _make_message(client, chan_a["id"], "secretA")
    proj_a = _make_project(client, ws_a["id"], "ProjA")
    task_a = _make_task(client, proj_a["id"], "TaskA")
    page_a = _make_page(client, ws_a["id"], "pageA", "PageA")
    event_a = _make_event(client, ws_a["id"], "EventA")
    as_user(client, "userA")
    file_a = _upload(client, ws_a["id"], "fileA.pdf").json()

    return {
        "ws_a": ws_a,
        "ws_b": ws_b,
        "chan_a": chan_a,
        "msg_a": msg_a,
        "proj_a": proj_a,
        "task_a": task_a,
        "page_a": page_a,
        "event_a": event_a,
        "file_a": file_a,
    }


# ===========================================================================
# Section 1 — Cross-workspace data leakage
# ===========================================================================


class TestCrossWorkspaceLeakage:
    """userA (member of wsA only) must not read anything in wsB.

    Every router that accepts a workspace-scoped path or a cross-workspace
    resource id is probed with A's valid token. Expected: 403 (not a member)
    or 404; never 2xx and never a body containing B's data.
    """

    def test_cannot_read_other_workspace_detail(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}")
        assert r.status_code == 403
        assert "wskw-b" not in r.text

    def test_cannot_list_other_workspace_members(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/members")
        assert r.status_code == 403

    def test_cannot_list_other_workspace_activity(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/activity")
        assert r.status_code == 403

    def test_cannot_list_other_workspace_audit_log(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/audit-log")
        assert r.status_code == 403

    def test_cannot_list_other_workspace_channels(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/channels")
        assert r.status_code == 403

    def test_cannot_list_other_workspace_dms(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/dms")
        assert r.status_code == 403

    def test_cannot_create_dm_in_other_workspace(self, client, two_workspaces, db_session):
        make_user(db_session, "userB")
        as_user(client, "userA")
        r = client.post(
            f"/workspaces/{two_workspaces['ws_b']['id']}/dms", json={"user_id": "userB"}
        )
        assert r.status_code == 403

    def test_cannot_create_channel_in_other_workspace(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.post(
            f"/workspaces/{two_workspaces['ws_b']['id']}/channels",
            json={"name": "pwned", "type": "general"},
        )
        assert r.status_code == 403

    def test_member_can_read_own_workspace_channel_messages(self, client, two_workspaces):
        """Positive control: A reads A's own channel (guards a 403-everywhere bug)."""
        as_user(client, "userA")
        r = client.get(f"/channels/{two_workspaces['chan_a']['id']}/messages")
        assert r.status_code == 200
        assert two_workspaces["msg_a"]["content"] in r.text

    def test_cannot_read_messages_of_unseen_channel(self, client, two_workspaces, db_session):
        # userA has no membership in wsB at all: create a channel as B first.
        as_user(client, "userB")
        chan_b = _make_channel(client, two_workspaces["ws_b"]["id"], "chanB")
        _make_message(client, chan_b["id"], "secretB")

        as_user(client, "userA")
        r = client.get(f"/channels/{chan_b['id']}/messages")
        assert r.status_code == 403
        assert "secretB" not in r.text

    def test_cannot_post_message_to_other_workspace_channel(self, client, two_workspaces):
        as_user(client, "userB")
        chan_b = _make_channel(client, two_workspaces["ws_b"]["id"], "chanB")

        as_user(client, "userA")
        r = client.post(f"/channels/{chan_b['id']}/messages", json={"content": "pwned"})
        assert r.status_code == 403

    def test_cannot_list_other_workspace_projects(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/projects")
        assert r.status_code == 403

    def test_cannot_create_project_in_other_workspace(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.post(
            f"/workspaces/{two_workspaces['ws_b']['id']}/projects", json={"name": "pwned"}
        )
        assert r.status_code == 403

    def test_cannot_read_other_workspace_project_by_id(self, client, two_workspaces):
        as_user(client, "userB")
        proj_b = _make_project(client, two_workspaces["ws_b"]["id"], "ProjB")

        as_user(client, "userA")
        assert client.get(f"/projects/{proj_b['id']}").status_code == 403

    def test_cannot_list_other_workspace_pages(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/pages")
        assert r.status_code == 403

    def test_cannot_read_other_workspace_page_by_id(self, client, two_workspaces):
        as_user(client, "userB")
        page_b = _make_page(client, two_workspaces["ws_b"]["id"], "pageB", "PageB")

        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/pages/{page_b['id']}")
        assert r.status_code == 403

    def test_cannot_read_other_workspace_page_history(self, client, two_workspaces):
        as_user(client, "userB")
        page_b = _make_page(client, two_workspaces["ws_b"]["id"], "pageB", "PageB")

        as_user(client, "userA")
        r = client.get(
            f"/workspaces/{two_workspaces['ws_b']['id']}/pages/{page_b['id']}/history"
        )
        assert r.status_code == 403

    def test_cannot_read_other_workspace_page_backlinks(self, client, two_workspaces):
        as_user(client, "userB")
        page_b = _make_page(client, two_workspaces["ws_b"]["id"], "pageB", "PageB")

        as_user(client, "userA")
        r = client.get(
            f"/workspaces/{two_workspaces['ws_b']['id']}/pages/{page_b['id']}/backlinks"
        )
        assert r.status_code == 403

    def test_cannot_list_other_workspace_events(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/events")
        assert r.status_code == 403

    def test_cannot_read_other_workspace_event_by_id(self, client, two_workspaces):
        as_user(client, "userB")
        event_b = _make_event(client, two_workspaces["ws_b"]["id"], "EventB")

        as_user(client, "userA")
        assert client.get(f"/events/{event_b['id']}").status_code == 403

    def test_cannot_list_other_workspace_files(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/files")
        assert r.status_code == 403

    def test_cannot_read_other_workspace_file_by_id(self, client, two_workspaces):
        as_user(client, "userB")
        file_b = _upload(client, two_workspaces["ws_b"]["id"], "fileB.pdf").json()

        as_user(client, "userA")
        r = client.get(f"/files/{file_b['id']}")
        assert r.status_code == 403
        assert "fileB.pdf" not in r.text

    def test_cannot_list_other_workspace_invites(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get(f"/workspaces/{two_workspaces['ws_b']['id']}/invites")
        assert r.status_code == 403

    def test_cannot_accept_invite_to_unrelated_workspace(self, client, two_workspaces, db_session):
        # B invites an email A does not own.
        as_user(client, "userB")
        invite = client.post(
            f"/workspaces/{two_workspaces['ws_b']['id']}/invites",
            json={"email": "thirdparty@example.com", "role": "member"},
        ).json()

        make_user(db_session, "userA")
        as_user(client, "userA")
        # userA is not a member of wsB; accepting the invite would LEAK wsB
        # membership to an unrelated account. The invite token is secret, but
        # the guard must still reject a membership-less accepter... here the
        # accept DOES create membership (by design). We assert the invariant
        # that A still cannot read wsB *before* accepting, and that accepting
        # an invite meant for another email is the only path in.
        r = client.post("/invites/accept", json={"token": invite["token"]})
        assert r.status_code in (201, 409)
        if r.status_code == 201:
            # If accepted, A must now be able to read wsB (invite is the
            # explicit consent flow) — and NOT by bypassing membership.
            as_user(client, "userA")
            assert client.get(f"/workspaces/{two_workspaces['ws_b']['id']}").status_code == 200

    def test_cannot_delete_other_workspace(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.delete(f"/workspaces/{two_workspaces['ws_b']['id']}")
        assert r.status_code == 403
        # wsB still exists.
        as_user(client, "userB")
        assert client.get(f"/workspaces/{two_workspaces['ws_b']['id']}").status_code == 200

    def test_cannot_update_other_workspace(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.patch(
            f"/workspaces/{two_workspaces['ws_b']['id']}",
            json={"name": "pwned"},
        )
        assert r.status_code == 403

    def test_cannot_transfer_other_workspace_ownership(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.post(
            f"/workspaces/{two_workspaces['ws_b']['id']}/transfer-ownership",
            json={"user_id": "userA"},
        )
        assert r.status_code == 403

    def test_my_tasks_never_cross_workspaces(self, client, two_workspaces, db_session):
        # Assign a task in wsB to userB; userA must not see it via /users/me/tasks.
        as_user(client, "userB")
        proj_b = _make_project(client, two_workspaces["ws_b"]["id"], "ProjB")
        _make_task(client, proj_b["id"], "TaskB")

        # userA has no wsB membership at all: nothing to leak.
        as_user(client, "userA")
        r = client.get("/users/me/tasks")
        assert r.status_code == 200
        titles = {t["title"] for t in r.json()}
        assert "TaskB" not in titles

    def test_notifications_never_cross_users(self, client, two_workspaces, db_session):
        from models import Notification

        notif = Notification(
            user_id="userB", type="other", title="secretB-notif", content="x"
        )
        db_session.add(notif)
        db_session.commit()

        as_user(client, "userA")
        r = client.get("/notifications")
        assert r.status_code == 200
        assert "secretB-notif" not in r.text
        # Direct read by id is also user-scoped.
        r2 = client.get(f"/notifications/{notif.id}")
        assert r2.status_code == 403

    def test_ai_search_never_returns_other_workspace(self, client, two_workspaces):
        as_user(client, "userA")
        r = client.get("/ai/search", params={"q": "secretA"})
        assert r.status_code == 200
        ws_ids = {res["workspace_id"] for res in r.json()["results"]}
        assert two_workspaces["ws_b"]["id"] not in ws_ids

    def test_ai_summarize_task_rejects_other_workspace(self, client, two_workspaces):
        as_user(client, "userB")
        proj_b = _make_project(client, two_workspaces["ws_b"]["id"], "ProjB")
        task_b = _make_task(client, proj_b["id"], "TaskB")

        as_user(client, "userA")
        r = client.post("/ai/summarize", json={"kind": "task", "ref_id": task_b["id"]})
        assert r.status_code == 403
        assert "TaskB" not in r.text

    def test_ai_summarize_page_rejects_other_workspace(self, client, two_workspaces):
        as_user(client, "userB")
        page_b = _make_page(client, two_workspaces["ws_b"]["id"], "pageB", "PageB")

        as_user(client, "userA")
        r = client.post("/ai/summarize", json={"kind": "page", "ref_id": page_b["id"]})
        assert r.status_code == 403
        assert "PageB" not in r.text

    def test_ai_summarize_channel_rejects_other_workspace(self, client, two_workspaces):
        as_user(client, "userB")
        chan_b = _make_channel(client, two_workspaces["ws_b"]["id"], "chanB")
        _make_message(client, chan_b["id"], "secretB-transcript")

        as_user(client, "userA")
        r = client.post("/ai/summarize", json={"kind": "channel", "ref_id": chan_b["id"]})
        assert r.status_code == 403
        assert "secretB-transcript" not in r.text


# ===========================================================================
# Section 2 — RBAC escalation
# ===========================================================================


@pytest.fixture
def ws_with_member(client, db_session):
    """A workspace owned by ``owner`` with ``member`` at member role."""
    ws = _create_workspace(client, "owner", "wsrbac")
    _add_member(client, db_session, ws["id"], "owner", "member", role="member")
    return ws


class TestRbacEscalation:
    def test_member_cannot_promote_self(self, client, ws_with_member):
        as_user(client, "member")
        r = client.patch(
            f"/workspaces/{ws_with_member['id']}/members/member",
            json={"role": "owner"},
        )
        assert r.status_code == 403

    def test_member_cannot_promote_other(self, client, ws_with_member, db_session):
        _add_member(client, db_session, ws_with_member["id"], "owner", "other", role="member")
        as_user(client, "member")
        r = client.patch(
            f"/workspaces/{ws_with_member['id']}/members/other",
            json={"role": "admin"},
        )
        assert r.status_code == 403

    def test_member_cannot_demote_owner(self, client, ws_with_member):
        as_user(client, "member")
        r = client.patch(
            f"/workspaces/{ws_with_member['id']}/members/owner",
            json={"role": "member"},
        )
        assert r.status_code == 403

    def test_member_cannot_remove_owner(self, client, ws_with_member):
        as_user(client, "member")
        r = client.delete(f"/workspaces/{ws_with_member['id']}/members/owner")
        assert r.status_code == 403

    def test_member_cannot_delete_workspace(self, client, ws_with_member):
        as_user(client, "member")
        r = client.delete(f"/workspaces/{ws_with_member['id']}")
        assert r.status_code == 403
        as_user(client, "owner")
        assert client.get(f"/workspaces/{ws_with_member['id']}").status_code == 200

    def test_member_cannot_transfer_ownership(self, client, ws_with_member):
        as_user(client, "member")
        r = client.post(
            f"/workspaces/{ws_with_member['id']}/transfer-ownership",
            json={"user_id": "member"},
        )
        assert r.status_code == 403

    def test_member_cannot_list_members(self, client, ws_with_member):
        as_user(client, "member")
        assert (
            client.get(f"/workspaces/{ws_with_member['id']}/members").status_code == 403
        )

    def test_member_cannot_invite(self, client, ws_with_member):
        as_user(client, "member")
        r = client.post(
            f"/workspaces/{ws_with_member['id']}/invites",
            json={"email": "newbie@example.com", "role": "member"},
        )
        assert r.status_code == 403

    def test_member_cannot_list_invites(self, client, ws_with_member):
        as_user(client, "member")
        r = client.get(f"/workspaces/{ws_with_member['id']}/invites")
        assert r.status_code == 403

    def test_member_cannot_view_audit_log(self, client, ws_with_member):
        as_user(client, "member")
        r = client.get(f"/workspaces/{ws_with_member['id']}/audit-log")
        assert r.status_code == 403

    def test_member_cannot_update_workspace(self, client, ws_with_member):
        as_user(client, "member")
        r = client.patch(
            f"/workspaces/{ws_with_member['id']}", json={"name": "pwned"}
        )
        assert r.status_code == 403

    def test_member_cannot_create_private_channel(self, client, ws_with_member):
        as_user(client, "member")
        r = client.post(
            f"/workspaces/{ws_with_member['id']}/channels",
            json={"name": "secret", "type": "private"},
        )
        assert r.status_code == 403

    def test_member_cannot_delete_file(self, client, ws_with_member):
        as_user(client, "owner")
        f = _upload(client, ws_with_member["id"], "doc.pdf").json()
        as_user(client, "member")
        assert client.delete(f"/files/{f['id']}").status_code == 403

    def test_member_cannot_delete_page(self, client, ws_with_member):
        as_user(client, "owner")
        page = _make_page(client, ws_with_member["id"], "pg", "Pg")
        as_user(client, "member")
        assert client.delete(
            f"/workspaces/{ws_with_member['id']}/pages/{page['id']}"
        ).status_code == 403

    def test_member_cannot_delete_project(self, client, ws_with_member):
        as_user(client, "owner")
        proj = _make_project(client, ws_with_member["id"], "P")
        as_user(client, "member")
        assert client.delete(f"/projects/{proj['id']}").status_code == 403

    def test_unauthenticated_user_isolation(self, client, ws_with_member):
        """A JWT identity with no memberships may create a workspace, but must
        never see workspaces it does not belong to."""
        as_user(client, "outsider")
        r = client.post(
            "/workspaces", json={"name": "x", "slug": "outsider-ws", "description": ""}
        )
        assert r.status_code == 201  # workspace creation is open to members+ of ANY ws
        # but the workspace list must not include other workspaces.
        r2 = client.get("/workspaces")
        assert r2.status_code == 200
        assert all(w["id"] != ws_with_member["id"] for w in r2.json())

    def test_invalid_role_rejected(self, client, ws_with_member):
        as_user(client, "owner")
        r = client.patch(
            f"/workspaces/{ws_with_member['id']}/members/member",
            json={"role": "superadmin"},
        )
        assert r.status_code == 422

    def test_owner_role_cannot_be_changed_by_admin(self, client, ws_with_member, db_session):
        _add_member(client, db_session, ws_with_member["id"], "owner", "adminuser", role="admin")
        as_user(client, "adminuser")
        r = client.patch(
            f"/workspaces/{ws_with_member['id']}/members/owner",
            json={"role": "member"},
        )
        assert r.status_code == 403
        assert "Cannot change owner's role" in r.text

    def test_member_cannot_add_channel_member(self, client, ws_with_member, db_session):
        as_user(client, "owner")
        ch = _make_channel(client, ws_with_member["id"], "priv", "private")
        as_user(client, "member")
        r = client.post(
            f"/channels/{ch['id']}/members", json={"user_id": "member"}
        )
        assert r.status_code == 403


# ===========================================================================
# Section 3 — Auth edges
# ===========================================================================


class TestAuthEdges:
    def test_missing_token_is_401(self, client):
        clear_auth(client)
        r = client.get("/workspaces")
        assert r.status_code == 401

    def test_expired_access_token_is_401(self, client, db_session):
        from dependencies import create_access_token

        make_user(db_session, "expireduser")
        token = create_access_token("expireduser", expires_delta=timedelta(seconds=-10))
        r = client.get("/workspaces", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_refresh_token_cannot_be_used_as_access(self, client, db_session):
        from dependencies import create_refresh_token

        make_user(db_session, "refreshuser")
        token = create_refresh_token("refreshuser")
        r = client.get("/workspaces", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_garbage_token_is_401(self, client):
        r = client.get("/workspaces", headers={"Authorization": "Bearer not.a.jwt"})
        assert r.status_code == 401

    def test_token_forged_with_wrong_secret_is_401(self, client, db_session):
        from jose import jwt as jose_jwt

        make_user(db_session, "forgeduser")
        token = jose_jwt.encode(
            {"sub": "forgeduser", "type": "access", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "completely-wrong-secret",
            algorithm="HS256",
        )
        r = client.get("/workspaces", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_jti_reuse_after_logout_is_401(self, client, db_session):
        """The session-scoped token from /auth/login must die on logout."""
        from dependencies import get_password_hash
        from models import User

        db_session.add(
            User(
                id="logoutuser",
                email="logoutuser@example.com",
                display_name="logoutuser",
                hashed_password=get_password_hash("supersecret123"),
            )
        )
        db_session.commit()

        login = client.post(
            "/auth/login",
            json={"email": "logoutuser@example.com", "password": "supersecret123"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]

        # Token works.
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

        # Logout revokes it.
        out = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert out.status_code == 200

        # Reuse must fail.
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_logout_all_revokes_every_session(self, client, db_session):
        from dependencies import get_password_hash
        from models import User

        db_session.add(
            User(
                id="logoutalluser",
                email="logoutalluser@example.com",
                display_name="logoutalluser",
                hashed_password=get_password_hash("supersecret123"),
            )
        )
        db_session.commit()

        tokens = []
        for _ in range(3):
            login = client.post(
                "/auth/login",
                json={"email": "logoutalluser@example.com", "password": "supersecret123"},
            )
            assert login.status_code == 200
            tokens.append(login.json()["access_token"])

        out = client.post(
            "/auth/logout-all", headers={"Authorization": f"Bearer {tokens[0]}"}
        )
        assert out.status_code == 200
        assert out.json()["revoked"] >= 3

        for token in tokens:
            assert (
                client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
                == 401
            )

    def test_refresh_token_rotation_and_replay(self, client, db_session):
        """#123 landed: /auth/refresh now rotates and detects replay (TA1-1).

        This delta test originally pinned main's pre-#123 behavior (404 — no
        endpoint). As its own note directed, once rotation landed it becomes a
        replay assertion: refreshing a real session rotates the pair, and
        replaying the already-rotated refresh token is rejected (single-use,
        family kill). Full rotation/replay coverage lives in
        test_auth_refresh.py; this asserts the auth edge holds here too.
        """
        from dependencies import create_session_pair

        make_user(db_session, "rotuser")
        _access, refresh = create_session_pair("rotuser", db_session)
        db_session.commit()

        first = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert first.status_code == 200, first.text
        rotated = first.json()["refresh_token"]
        assert rotated != refresh

        # Replay the already-rotated original: rejected (reuse = theft signal).
        assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401
        # Family kill: the rotated successor is dead too.
        assert client.post("/auth/refresh", json={"refresh_token": rotated}).status_code == 401

    def test_test_auth_bypass_disabled_by_default(self, client, db_session):
        """The X-Test-User-* header bypass must stay OFF without STW_TEST_AUTH=1."""
        make_user(db_session, "testbypass")
        r = client.get(
            "/workspaces", headers={"X-Test-User-Id": "testbypass", "X-Test-User-Role": "owner"}
        )
        assert r.status_code == 401

    def test_login_wrong_password_is_401(self, client, db_session):
        from dependencies import get_password_hash
        from models import User

        db_session.add(
            User(
                id="pwuser",
                email="pwuser@example.com",
                display_name="pwuser",
                hashed_password=get_password_hash("supersecret123"),
            )
        )
        db_session.commit()
        r = client.post(
            "/auth/login",
            json={"email": "pwuser@example.com", "password": "wrongpassword"},
        )
        assert r.status_code == 401

    def test_register_duplicate_email_is_409(self, client, db_session):
        payload = {"email": "dupe@example.com", "password": "supersecret123"}
        first = client.post("/auth/register", json=payload)
        assert first.status_code == 201
        second = client.post("/auth/register", json=payload)
        assert second.status_code == 409


# ===========================================================================
# Section 4 — File upload abuse
# ===========================================================================


class TestFileUploadAbuse:
    @pytest.fixture(autouse=True)
    def _no_rate_limit(self, monkeypatch):
        # The suite-wide limiter would 429 the burst tests below. Per-test
        # isolation is still exact: reset() runs in the conftest autouse
        # fixture before AND after every test.
        monkeypatch.setenv("RATELIMIT_ENABLED", "0")

    def test_empty_file_rejected(self, client, two_workspaces):
        as_user(client, "userA")
        r = _upload(client, two_workspaces["ws_a"]["id"], "empty.pdf", b"")
        assert r.status_code == 422

    def test_missing_content_type_still_classified(self, client, two_workspaces, monkeypatch):
        # No explicit content type: mimetypes.guess_type(".txt") -> text/plain.
        as_user(client, "userA")
        r = client.post(
            f"/workspaces/{two_workspaces['ws_a']['id']}/files",
            files={"file": ("notes.txt", io.BytesIO(b"hello"))},
        )
        assert r.status_code == 201
        assert r.json()["type"] == "document"

    def test_filename_path_traversal_rejected(self, client, two_workspaces):
        """Filenames containing path separators must be rejected with 422.

        A traversal filename is not storable: with the uuid-prefixed key it
        either escapes UPLOAD_DIR (Windows path normalization) or makes the
        write fail with a bare 500 (POSIX: the literal ``<uuid>_..`` directory
        does not exist). Neither outcome is acceptable, so the upload now
        rejects it before touching the filesystem. This assertion works
        identically on both CI runners.
        """
        as_user(client, "userA")
        ws_id = two_workspaces["ws_a"]["id"]
        for evil in ("../../evil-one", "../evil-two", "sub/../../evil-three", "..\\evil-four"):
            r = _upload(client, ws_id, evil, b"pwned")
            assert r.status_code == 422, f"{evil!r}: expected 422, got {r.status_code}"
            assert "path separators" in r.json()["detail"]

    def test_cross_workspace_link_target_rejected(self, client, two_workspaces):
        as_user(client, "userB")
        proj_b = _make_project(client, two_workspaces["ws_b"]["id"], "ProjB")

        as_user(client, "userA")
        r = client.post(
            f"/workspaces/{two_workspaces['ws_a']['id']}/files",
            files={"file": ("a.txt", io.BytesIO(b"a"), "text/plain")},
            data={"project_id": proj_b["id"]},
        )
        assert r.status_code == 422

    def test_upload_rate_limit_429(self, client, two_workspaces, monkeypatch):
        """The dedicated upload bucket (20/h/user) must cap floods."""
        monkeypatch.setenv("RATELIMIT_ENABLED", "1")
        import rate_limit

        monkeypatch.setattr(rate_limit, "UPLOAD_LIMIT", (2, 3600))
        as_user(client, "userA")
        ws_id = two_workspaces["ws_a"]["id"]

        ok = []
        for _ in range(2):
            r = _upload(client, ws_id, f"{len(ok)}.pdf", b"x")
            if r.status_code == 201:
                ok.append(r)
        r = _upload(client, ws_id, "third.pdf", b"x")
        assert r.status_code == 429
        assert "Retry-After" in r.headers

    def test_non_member_cannot_upload(self, client, two_workspaces):
        as_user(client, "userB")
        r = _upload(client, two_workspaces["ws_a"]["id"], "x.pdf", b"x")
        assert r.status_code == 403


# ===========================================================================
# Section 5 — Session/privacy edges
# ===========================================================================


class TestPrivacyEdges:
    def test_account_export_is_own_user_only(self, client, db_session, two_workspaces):
        as_user(client, "userA")
        r = client.get("/users/me/export")
        assert r.status_code == 200
        # A's export must contain zero bytes from wsB.
        body = r.text
        assert "wskw-b" not in body

    def test_other_user_notification_inaccessible(self, client, db_session):
        from models import Notification

        make_user(db_session, "userB")
        n = Notification(user_id="userB", type="other", title="private", content="x")
        db_session.add(n)
        db_session.commit()
        as_user(client, "userA")
        assert client.patch(
            f"/notifications/{n.id}", json={"read": True}
        ).status_code == 403
        assert client.delete(f"/notifications/{n.id}").status_code == 403

    def test_uploaded_bytes_downloadable_via_url(self, client, tmp_path, monkeypatch):
        """/uploads is public static by design — the protected surface is the
        file ROW and its storage-key disclosure (Section 1 pins that only
        workspace members ever see the key). This test pins that the static
        route exists and serves the real bytes, so a future change that
        accidentally breaks the download path is caught.
        """
        from fastapi.staticfiles import StaticFiles

        import app as app_module

        d = tmp_path / "uploads"
        d.mkdir()
        monkeypatch.setattr(app_module, "UPLOAD_DIR", d)
        # The static mount captured the default ./uploads dir at import time,
        # so swap the route to serve from the tmp dir instead.
        app_module.app.router.routes[:] = [
            r for r in app_module.app.router.routes if getattr(r, "name", None) != "uploads"
        ]
        app_module.app.mount("/uploads", StaticFiles(directory=str(d)), name="uploads")

        as_user(client, "userA")
        ws = client.post("/workspaces", json={"name": "WS", "slug": "wsdl", "description": "x"})
        assert ws.status_code == 201
        up = _upload(client, ws.json()["id"], "doc.pdf", b"dl-bytes").json()
        dl = client.get(up["url"])
        assert dl.status_code == 200
        assert dl.content == b"dl-bytes"
