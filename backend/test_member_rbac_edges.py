"""Regression tests for workspace membership edges (routers/members.py).

The existing suite covers the happy paths and the owner-protection rules. These
tests cover the branches that were only ever executed as side effects of
rate-limit tests (whose assertions are about 429s, not the member semantics):

* listing members is itself admin-gated (a plain member reading the roster);
* a member role update for a user who is NOT a member of that workspace (404,
  not a silent create and not a 403 that hides the real state);
* an invalid role value in the PATCH body (400, not 500 from a ValueError);
* removing a user who was never a member (404);
* removing a user from a workspace they already left is idempotent-fail (404);
* the dead "cannot change your own role as owner" self-check is provably
  unreachable without the earlier owner guard — documented, not relied on.

Every assertion is on observable behavior (status + persisted role), so a
regression in any branch fails the test rather than merely dropping coverage.
"""

import pytest
from fastapi import HTTPException

from app import Role
from conftest import as_user, clear_auth, make_user
from models import Workspace, WorkspaceMembership

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def setup(db_session, client):
    """A workspace owned by ``owner`` with an admin and a plain member."""
    make_user(db_session, "owner", email="owner@example.com")
    make_user(db_session, "admin1", email="admin1@example.com")
    make_user(db_session, "member1", email="member1@example.com")
    make_user(db_session, "outsider", email="outsider@example.com")

    ws = Workspace(name="Members Edge", slug="members-edge")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="owner", role=Role.OWNER.value)
    )
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="admin1", role=Role.ADMIN.value)
    )
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="member1", role=Role.MEMBER.value)
    )
    db_session.commit()
    return {"workspace_id": ws.id}


def _role_of(db_session, workspace_id, user_id):
    m = (
        db_session.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        .first()
    )
    return m.role if m else None


# ---------------------------------------------------------------------------
# LIST members is itself gated
# ---------------------------------------------------------------------------


def test_member_cannot_list_members(setup, client, db_session):
    """workspace.manage_members maps to ADMIN; a member reading the roster is 403."""
    ws_id = setup["workspace_id"]
    as_user(client, "member1")
    resp = client.get(f"/workspaces/{ws_id}/members")
    assert resp.status_code == 403, resp.text


def test_admin_can_list_members_includes_user_rows(setup, client, db_session):
    """The roster is admin-visible and eager-loads the user profile."""
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    resp = client.get(f"/workspaces/{ws_id}/members")
    assert resp.status_code == 200, resp.text
    by_user = {m["user_id"]: m for m in resp.json()}
    assert set(by_user) == {"owner", "admin1", "member1"}
    # selectinload(user) must populate the nested profile, not leave it null.
    assert by_user["member1"]["user"]["email"] == "member1@example.com"
    assert by_user["member1"]["role"] == Role.MEMBER.value


def test_non_member_cannot_list_members(setup, client, db_session):
    """A stranger is refused by RBAC before any roster data is returned."""
    ws_id = setup["workspace_id"]
    as_user(client, "outsider")
    resp = client.get(f"/workspaces/{ws_id}/members")
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# PATCH /members/{user_id} edges
# ---------------------------------------------------------------------------


def test_promote_non_member_returns_404(setup, client, db_session):
    """Targeting a user with no membership row is 404, never a silent create."""
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    resp = client.patch(
        f"/workspaces/{ws_id}/members/outsider", json={"role": Role.ADMIN.value}
    )
    assert resp.status_code == 404, resp.text
    assert "Member not found" in resp.json()["detail"]
    # And nothing was created.
    assert _role_of(db_session, ws_id, "outsider") is None


def test_invalid_role_value_returns_422_via_http(setup, client, db_session):
    """An invalid role is rejected by the schema (Literal) at 422, not 500.

    Note: this means the router's own ``try: Role(payload.role)`` branch is
    defense-in-depth for direct caller misuse, not the primary guard. The
    next test exercises it directly so it is proven, not assumed.
    """
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    resp = client.patch(
        f"/workspaces/{ws_id}/members/member1", json={"role": "superuser"}
    )
    assert resp.status_code == 422, resp.text
    # The member's role is untouched.
    assert _role_of(db_session, ws_id, "member1") == Role.MEMBER.value


def test_router_invalid_role_branch_is_400_not_500(setup, db_session):
    """Direct-call proof that a non-Literal role value yields 400, never 500.

    A caller bypassing pydantic (e.g. an internal service passing a raw
    object) must still get a clean 400 instead of an unhandled ValueError.
    """
    import asyncio
    from types import SimpleNamespace

    from routers.members import update_member_role

    ws_id = setup["workspace_id"]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            update_member_role(
                workspace_id=ws_id,
                user_id="member1",
                payload=SimpleNamespace(role="superuser"),
                current_user={"id": "admin1"},
                db=db_session,
            )
        )
    assert exc.value.status_code == 400
    assert "Invalid role" in exc.value.detail
    assert _role_of(db_session, ws_id, "member1") == Role.MEMBER.value


def test_promote_member_to_admin_persists(setup, client, db_session):
    """The happy path the coverage gap was hiding: a real persisted promotion."""
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    resp = client.patch(
        f"/workspaces/{ws_id}/members/member1", json={"role": Role.ADMIN.value}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == Role.ADMIN.value
    # Persisted, not just returned.
    db_session.expire_all()
    assert _role_of(db_session, ws_id, "member1") == Role.ADMIN.value


def test_demote_self_admin_to_member_blocked_by_owner_protection(setup, client):
    """An admin cannot demote the owner (the owner guard fires first)."""
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    resp = client.patch(
        f"/workspaces/{ws_id}/members/owner", json={"role": Role.MEMBER.value}
    )
    assert resp.status_code == 403, resp.text
    assert "Cannot change owner's role" in resp.json()["detail"]


def test_owner_self_patch_guard_is_unreachable(setup, client):
    """The 'cannot change your own role as owner' branch is dead by construction.

    The owner check (role == owner) precedes it and always fires for an owner
    self-patch. This test pins that ordering so a future refactor cannot make
    the dead branch the ONLY guard (which would let an owner demote someone
    else's owner row through a different code path).
    """
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    resp = client.patch(
        f"/workspaces/{ws_id}/members/owner", json={"role": Role.MEMBER.value}
    )
    # The FIRST guard (role == owner) wins; the detail proves which one fired.
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Cannot change owner's role"


# ---------------------------------------------------------------------------
# DELETE /members/{user_id} edges
# ---------------------------------------------------------------------------


def test_remove_member_persists_and_lists_shrink(setup, client, db_session):
    """Removing a member actually deletes the row (not just a 204)."""
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    resp = client.delete(f"/workspaces/{ws_id}/members/member1")
    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    assert _role_of(db_session, ws_id, "member1") is None

    as_user(client, "admin1")
    roster = {m["user_id"] for m in client.get(f"/workspaces/{ws_id}/members").json()}
    assert roster == {"owner", "admin1"}


def test_remove_nonexistent_member_returns_404(setup, client, db_session):
    """Removing a stranger yields 404 and does not create or delete anything."""
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    resp = client.delete(f"/workspaces/{ws_id}/members/outsider")
    assert resp.status_code == 404, resp.text
    assert "Member not found" in resp.json()["detail"]


def test_remove_member_twice_is_404(setup, client):
    """Idempotency check: the second removal finds no row."""
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    assert client.delete(f"/workspaces/{ws_id}/members/member1").status_code == 204
    as_user(client, "admin1")
    resp = client.delete(f"/workspaces/{ws_id}/members/member1")
    assert resp.status_code == 404, resp.text


def test_admin_cannot_remove_owner(setup, client, db_session):
    ws_id = setup["workspace_id"]
    as_user(client, "admin1")
    resp = client.delete(f"/workspaces/{ws_id}/members/owner")
    assert resp.status_code == 403, resp.text
    assert "Cannot remove workspace owner" in resp.json()["detail"]
    db_session.expire_all()
    assert _role_of(db_session, ws_id, "owner") == Role.OWNER.value


def test_member_cannot_remove_other_member(setup, client, db_session):
    """member.remove maps to ADMIN; a member removing someone is 403."""
    ws_id = setup["workspace_id"]
    as_user(client, "member1")
    resp = client.delete(f"/workspaces/{ws_id}/members/admin1")
    assert resp.status_code == 403, resp.text
    db_session.expire_all()
    assert _role_of(db_session, ws_id, "admin1") == Role.ADMIN.value


def test_remove_member_from_wrong_workspace_404(setup, client, db_session):
    """A user who is a member of workspace A cannot be removed from workspace B."""
    # A second workspace owned by outsider; member1 has no row there.
    ws_b = Workspace(name="Other WS", slug="other-ws-edge")
    db_session.add(ws_b)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws_b.id, user_id="outsider", role=Role.OWNER.value)
    )
    db_session.commit()

    as_user(client, "outsider")
    resp = client.delete(f"/workspaces/{ws_b.id}/members/member1")
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Anonymous / malformed auth never reaches member logic
# ---------------------------------------------------------------------------


def test_anonymous_cannot_list_members(setup, client):
    clear_auth(client)
    resp = client.get(f"/workspaces/{setup['workspace_id']}/members")
    assert resp.status_code == 401
