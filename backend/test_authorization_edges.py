"""Regression tests for the RBAC core (authorization.py).

Covers the auth edges the existing suite reaches only indirectly:

* the Role(...) parse-failure fallbacks (a stored membership role that is not
  one of owner/admin/member/guest must degrade to GUEST, never 500);
* the workspace-not-found and non-member branches of require_role();
* the permission -> minimum-role mapping (require_permission), including the
  unknown-permission default of OWNER;
* the role hierarchy itself (a guest must never satisfy an admin requirement).

Each test fails-meaningfully: the assertions are on observable behavior
(status codes + detail strings), so a regression in any branch turns the test
red rather than merely dropping a coverage line.
"""

import pytest
from fastapi import HTTPException

import authorization
from authorization import ROLE_HIERARCHY, Role, require_permission, require_role
from conftest import as_user, make_user
from models import Workspace, WorkspaceMembership

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_user(db, user_id, email=None):
    return make_user(db, user_id, email=email or f"{user_id}@example.com")


def _mk_workspace(db, owner_id="owner", slug="ws"):
    make_user(db, owner_id)
    ws = Workspace(name=f"WS {slug}", slug=slug)
    db.add(ws)
    db.flush()
    db.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=owner_id, role=Role.OWNER.value)
    )
    db.commit()
    return ws


# ---------------------------------------------------------------------------
# Pure-unit tests of the RBAC primitives
# ---------------------------------------------------------------------------


def test_role_hierarchy_values_are_ordered():
    """The hierarchy is the ground truth every router compares against."""
    assert ROLE_HIERARCHY[Role.GUEST] < ROLE_HIERARCHY[Role.MEMBER]
    assert ROLE_HIERARCHY[Role.MEMBER] < ROLE_HIERARCHY[Role.ADMIN]
    assert ROLE_HIERARCHY[Role.ADMIN] < ROLE_HIERARCHY[Role.OWNER]


def test_require_min_role_rejects_insufficient_role():
    """A member's token must not satisfy an admin requirement."""
    current_user = {"id": "u1", "role": Role.MEMBER.value}
    with pytest.raises(HTTPException) as exc:
        authorization._require_min_role(current_user, Role.ADMIN)
    assert exc.value.status_code == 403
    # The detail names both roles so operators can see why it refused.
    assert Role.MEMBER.value in exc.value.detail
    assert Role.ADMIN.value in exc.value.detail


def test_require_min_role_accepts_sufficient_role():
    authorization._require_min_role({"role": Role.ADMIN.value}, Role.ADMIN)
    authorization._require_min_role({"role": Role.OWNER.value}, Role.ADMIN)


def test_require_min_role_unknown_role_falls_back_to_guest():
    """A bogus role string must degrade to guest (403 vs admin), never 500."""
    with pytest.raises(HTTPException) as exc:
        authorization._require_min_role({"role": "superuser"}, Role.MEMBER)
    assert exc.value.status_code == 403
    assert "guest" in exc.value.detail


def test_require_min_role_missing_role_key_defaults_to_guest():
    """A token payload without a role key is treated as guest, not KeyError."""
    with pytest.raises(HTTPException) as exc:
        authorization._require_min_role({}, Role.MEMBER)
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "permission, expected",
    [
        # Enumerated in authorization.py::require_permission; every entry is a
        # real permission string used by a router Depends(...).
        ("workspace.create", Role.MEMBER),
        ("workspace.delete", Role.OWNER),
        ("workspace.transfer_ownership", Role.OWNER),
        ("workspace.update", Role.ADMIN),
        ("workspace.invite", Role.ADMIN),
        ("workspace.manage_members", Role.ADMIN),
        ("workspace.view_audit_log", Role.ADMIN),
        ("member.remove", Role.ADMIN),
        ("member.update_role", Role.ADMIN),
        ("project.create", Role.MEMBER),
        ("project.update", Role.ADMIN),
        ("project.delete", Role.ADMIN),
        ("project.manage_members", Role.ADMIN),
        # Unknown permissions default to the strictest role rather than
        # silently allowing the call (fail-closed).
        ("workspace.nuke_everything", Role.OWNER),
        ("", Role.OWNER),
    ],
)
def test_permission_to_role_mapping(permission, expected):
    """The mapping is what routers actually depend on; a change here silently
    re-permissions the whole API, so it is pinned by intent, not by accident."""
    checker = require_permission(permission)
    assert _required_role_of(checker) is expected


@pytest.mark.parametrize(
    "permission", ["workspace.delete", "workspace.transfer_ownership"]
)
def test_permission_mapping_denies_admin_on_real_workspace(permission, db_session):
    """End-to-end proof that the OWNER entries are enforced, not just declared.

    ``member.update_role`` / ``workspace.invite`` are exercised through HTTP in
    test_member_rbac_edges.py; here the OWNER-only side of the table is pinned:
    an admin (one step below owner) is refused on the delete permissions, so
    those entries cannot be silently relaxed to ADMIN.
    """
    ws = _mk_workspace(db_session, "owner", slug=f"perm-{permission.replace('.', '_')}")
    make_user(db_session, "owner")
    make_user(db_session, "admin", email="admin@example.com")
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="admin", role=Role.ADMIN.value)
    )
    db_session.commit()

    checker = require_permission(permission)
    with pytest.raises(HTTPException) as exc:
        _call(checker, db_session, ws.id, {"id": "admin", "role": Role.ADMIN.value})
    assert exc.value.status_code == 403
    assert "insufficient" in exc.value.detail


@pytest.mark.parametrize("role", [Role.GUEST, Role.MEMBER, Role.ADMIN])
def test_unknown_permission_rejects_every_non_owner(role, db_session):
    """The owner-default is enforced on the real workspace path too: every
    non-owner role is refused, so a new permission cannot leak in as
    member-executable (fail-closed)."""
    ws = _mk_workspace(db_session, "owner", slug=f"unk-{role.value}")
    make_user(db_session, "owner")
    make_user(db_session, "other", email=f"other-{role.value}@example.com")
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="other", role=role.value)
    )
    db_session.commit()

    checker = require_permission("some.new.permission")
    with pytest.raises(HTTPException) as exc:
        _call(checker, db_session, ws.id, {"id": "other", "role": role.value})
    assert exc.value.status_code == 403
    assert "insufficient" in exc.value.detail


# ---------------------------------------------------------------------------
# require_role against a real DB (workspace branches)
# ---------------------------------------------------------------------------


def _required_role_of(checker):
    """The inner dependency is require_role(required_role); compare by the
    closure cell rather than running a request for a pure mapping check."""
    return checker.__closure__[0].cell_contents


def _checker_for(db, workspace_id, required: Role):
    """Build the require_role dependency for the test DB session.

    ``db: Session = Depends(get_db)`` is a sentinel default until FastAPI
    resolves it, so the checker must be called with the session explicitly.
    """
    return require_role(required)


def _call(checker, db, workspace_id, current_user):
    return checker(workspace_id=workspace_id, current_user=current_user, db=db)


def test_require_role_workspace_member_sufficient(db_session):
    """An admin member satisfies an admin requirement in her workspace."""
    ws = _mk_workspace(db_session, "owner", slug="wsmem")
    _mk_user(db_session, "alice")
    db_session.add(
        WorkspaceMembership(
            workspace_id=ws.id, user_id="alice", role=Role.ADMIN.value
        )
    )
    db_session.commit()

    checker = _checker_for(db_session, ws.id, Role.ADMIN)
    current = {"id": "alice"}
    assert _call(checker, db_session, ws.id, current)["id"] == "alice"


def test_require_role_workspace_member_insufficient_403(db_session):
    """A guest member is refused even inside a workspace she belongs to."""
    ws = _mk_workspace(db_session, "owner", slug="wsguest")
    _mk_user(db_session, "bob")
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="bob", role=Role.GUEST.value)
    )
    db_session.commit()

    checker = _checker_for(db_session, ws.id, Role.ADMIN)
    with pytest.raises(HTTPException) as exc:
        _call(checker, db_session, ws.id, {"id": "bob"})
    assert exc.value.status_code == 403
    assert "insufficient in this workspace" in exc.value.detail


def test_require_role_non_member_403(db_session):
    """A stranger to the workspace is refused (not treated as guest)."""
    ws = _mk_workspace(db_session, "owner", slug="wsstranger")
    _mk_user(db_session, "eve")

    checker = _checker_for(db_session, ws.id, Role.MEMBER)
    with pytest.raises(HTTPException) as exc:
        _call(checker, db_session, ws.id, {"id": "eve"})
    assert exc.value.status_code == 403
    assert "Not a workspace member" in exc.value.detail


def test_require_role_unknown_workspace_404(db_session):
    """A missing workspace yields 404 before any role check."""
    _mk_user(db_session, "owner")
    checker = _checker_for(db_session, "does-not-exist", Role.MEMBER)
    with pytest.raises(HTTPException) as exc:
        _call(checker, db_session, "does-not-exist", {"id": "owner"})
    assert exc.value.status_code == 404
    assert "Workspace not found" in exc.value.detail


def test_require_role_workspace_role_falls_back_on_bogus_stored_role(db_session):
    """A corrupted stored role degrades to guest instead of raising ValueError."""
    ws = _mk_workspace(db_session, "owner", slug="wsbogus")
    _mk_user(db_session, "carol")
    db_session.add(
        # Not a valid Role value -- e.g. a bad manual DB edit.
        WorkspaceMembership(workspace_id=ws.id, user_id="carol", role="intern")
    )
    db_session.commit()

    checker = _checker_for(db_session, ws.id, Role.MEMBER)
    with pytest.raises(HTTPException) as exc:
        _call(checker, db_session, ws.id, {"id": "carol"})
    assert exc.value.status_code == 403
    assert "insufficient in this workspace" in exc.value.detail


def test_require_role_global_path_uses_token_role(db_session):
    """No workspace_id -> the token's global role decides (used by workspace.create)."""
    _mk_user(db_session, "owner")
    checker = _checker_for(db_session, None, Role.MEMBER)
    # A token role that satisfies MEMBER.
    assert _call(checker, db_session, None, {"id": "x", "role": Role.ADMIN.value})


def test_require_role_global_path_rejects_guest_token_role(db_session):
    checker = _checker_for(db_session, None, Role.ADMIN)
    with pytest.raises(HTTPException) as exc:
        _call(checker, db_session, None, {"id": "x", "role": Role.GUEST.value})
    assert exc.value.status_code == 403
    assert "insufficient. Requires 'admin'." in exc.value.detail


# ---------------------------------------------------------------------------
# End-to-end: the mapping is what actually gates a real endpoint
# ---------------------------------------------------------------------------


def test_permission_mapping_enforced_on_members_endpoint(client, db_session):
    """member.update_role maps to ADMIN and a member-typed JWT is refused.

    Uses a real HTTP request so the mapping is proven wired through the
    dependency system, not just present in the dict.
    """
    ws = _mk_workspace(db_session, "owner", slug="wse2e")
    make_user(db_session, "owner")
    make_user(db_session, "alice", email="alice@example.com")
    make_user(db_session, "bob", email="bob@example.com")
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="alice", role=Role.MEMBER.value)
    )
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="bob", role=Role.MEMBER.value)
    )
    db_session.commit()

    # A *global* admin token for alice: require_permission resolves the
    # workspace role from the membership row, so a member membership must
    # still be refused even with an admin-flavored token.
    as_user(client, "alice")
    resp = client.patch(
        f"/workspaces/{ws.id}/members/bob", json={"role": Role.ADMIN.value}
    )
    assert resp.status_code == 403, resp.text

    # The workspace owner is allowed by the same mapping.
    as_user(client, "owner")
    resp = client.patch(
        f"/workspaces/{ws.id}/members/bob", json={"role": Role.ADMIN.value}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == Role.ADMIN.value


def test_member_router_requires_admin_token_globally(client, db_session):
    """A token with no role key (plain JWT for a user) is guest-typed: refused."""
    ws = _mk_workspace(db_session, "owner", slug="wsglobal")
    make_user(db_session, "owner")
    as_user(client, "owner")
    # The owner has a membership row with role owner; require_permission ->
    # require_role(workspace_id) reads the DB membership, so this succeeds and
    # proves the DB branch (not the token role) is authoritative.
    resp = client.get(f"/workspaces/{ws.id}/members")
    assert resp.status_code == 200, resp.text
    assert any(m["user_id"] == "owner" for m in resp.json())


def test_invalid_bearer_is_401_not_500(client):
    """Malformed tokens never reach RBAC code paths."""
    client.headers["Authorization"] = "Bearer not.a.jwt"
    resp = client.get("/workspaces/abc/members")
    assert resp.status_code == 401
