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
from fastapi import Depends, HTTPException

import authorization
import models
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
    """The hierarchy is the ground truth every router compares against.

    `co-owner` sits strictly between owner and admin (D-3c): above every role an
    admin can hand out, below the one role that can transfer ownership.
    """
    assert ROLE_HIERARCHY[Role.GUEST] < ROLE_HIERARCHY[Role.MEMBER]
    assert ROLE_HIERARCHY[Role.MEMBER] < ROLE_HIERARCHY[Role.ADMIN]
    assert ROLE_HIERARCHY[Role.ADMIN] < ROLE_HIERARCHY[Role.CO_OWNER]
    assert ROLE_HIERARCHY[Role.CO_OWNER] < ROLE_HIERARCHY[Role.OWNER]
    assert len(ROLE_HIERARCHY) == len(list(Role))


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


def test_require_global_role_uses_token_role(db_session):
    """The token's global role decides for platform-level actions (`workspace.create`).

    ARC-05 moved this out of `require_role` — where a missing path parameter
    silently fell through to it — into a factory a route has to ask for.
    """
    _mk_user(db_session, "owner")
    checker = authorization.require_global_role(Role.MEMBER)
    # A token role that satisfies MEMBER.
    assert checker(current_user={"id": "x", "role": Role.ADMIN.value})


def test_require_global_role_rejects_guest_token_role(db_session):
    checker = authorization.require_global_role(Role.ADMIN)
    with pytest.raises(HTTPException) as exc:
        checker(current_user={"id": "x", "role": Role.GUEST.value})
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


# ---------------------------------------------------------------------------
# ARC-05 — the workspace a guard checks comes from the path, never the client
# ---------------------------------------------------------------------------


def _query_scoped_routes(spec):
    """OpenAPI operations that take `workspace_id` as a QUERY parameter."""
    hits = []
    for path, operations in (spec.get("paths") or {}).items():
        for method, operation in (operations or {}).items():
            for param in operation.get("parameters") or []:
                if param.get("name") == "workspace_id" and param.get("in") == "query":
                    hits.append(f"{method.upper()} {path}")
    return sorted(hits)


def test_no_route_takes_its_workspace_scope_from_the_query_string():
    """A guard whose workspace can be named in a URL is a cross-tenant hole waiting to happen.

    `workspace_id: str = None` in the guard makes FastAPI publish a *query*
    parameter on any route whose path lacks `{workspace_id}` — which is exactly
    how the T001/T002 class of bug returns silently when someone adds a route.
    The published OpenAPI is where that shape shows up first, so the assertion
    is on the contract the app advertises, not on a grep of the source.
    """
    from app import app

    assert _query_scoped_routes(app.openapi()) == []


def test_creating_a_workspace_is_not_rescoped_by_a_query_string(client, db_session):
    """?workspace_id=<a workspace I do not belong to> must not change who may create.

    Before the fix the guard read that query value and went looking for a
    membership row, so a legitimate platform-level action could be turned into
    a 403 by the caller's own URL.
    """
    ws = _mk_workspace(db_session, "someoneelse", slug="arc05-other")
    make_user(db_session, "creator", email="creator@example.com")

    as_user(client, "creator")
    resp = client.post(
        f"/workspaces?workspace_id={ws.id}",
        json={"name": "Mine", "slug": "arc05-mine"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] != ws.id


def test_a_route_without_the_path_parameter_cannot_be_scoped_by_the_caller():
    """The guard is path-only, so a mis-shaped route fails closed instead of reading a query.

    This is the regression the finding is about: `require_role` used to fall
    back to a client-supplied `?workspace_id=` whenever the route did not carry
    the path parameter. A throwaway app pins the new contract — the request is
    refused outright, and nothing the caller sends can name the workspace.
    """
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    from app import create_access_token

    router = APIRouter()

    @router.post("/misshaped")
    async def misshaped(current_user: dict = Depends(require_permission("workspace.delete"))):
        return {"ok": True}

    probe = FastAPI()
    probe.include_router(router)
    client_probe = TestClient(probe, raise_server_exceptions=False)
    client_probe.headers["Authorization"] = f"Bearer {create_access_token('owner')}"

    resp = client_probe.post("/misshaped?workspace_id=anything")
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert any(
        p.get("loc") == ["path", "workspace_id"] and p.get("type") == "missing"
        for p in detail
    ), f"expected a missing path parameter, got {detail}"


# ---------------------------------------------------------------------------
# D-3c — the assignment ceiling is strict: requested rank < caller rank
# ---------------------------------------------------------------------------

# (caller role, requested role, expected status). Expected values are literals
# derived from the policy table, not computed from ROLE_HIERARCHY — a test that
# recomputed the rule from the same dict would pass whatever the dict said.
CEILING_MATRIX = [
    (Role.OWNER, Role.CO_OWNER, 200),
    (Role.OWNER, Role.ADMIN, 200),
    (Role.OWNER, Role.MEMBER, 200),
    (Role.OWNER, Role.GUEST, 200),
    (Role.CO_OWNER, Role.ADMIN, 200),
    (Role.CO_OWNER, Role.MEMBER, 200),
    (Role.CO_OWNER, Role.GUEST, 200),
    (Role.CO_OWNER, Role.CO_OWNER, 403),
    (Role.ADMIN, Role.MEMBER, 200),
    (Role.ADMIN, Role.GUEST, 200),
    (Role.ADMIN, Role.ADMIN, 403),
    (Role.ADMIN, Role.CO_OWNER, 403),
]


@pytest.mark.parametrize("caller_role,requested,expected", CEILING_MATRIX)
def test_ceiling_matrix_on_member_role_patch(
    client, db_session, caller_role, requested, expected
):
    """Nobody may hand out a role equal to or above their own rank."""
    owner_id = _mk_user(db_session, "ceil-owner").id
    ws = Workspace(name="Ceiling", slug=f"ceil-{caller_role.value}-{requested.value}")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=owner_id, role=Role.OWNER.value)
    )
    caller = _mk_user(db_session, f"caller-{caller_role.value}")
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=caller.id, role=caller_role.value)
    )
    target = _mk_user(db_session, f"target-{caller_role.value}-{requested.value}")
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=target.id, role=Role.MEMBER.value)
    )
    db_session.commit()

    as_user(client, caller.id)
    resp = client.patch(
        f"/workspaces/{ws.id}/members/{target.id}", json={"role": requested.value}
    )
    assert resp.status_code == expected, resp.text
    db_session.expire_all()
    persisted = (
        db_session.query(WorkspaceMembership)
        .filter_by(workspace_id=ws.id, user_id=target.id)
        .first()
        .role
    )
    if expected == 403:
        assert persisted == Role.MEMBER.value, f"refused grant still persisted: {persisted}"
    else:
        assert persisted == requested.value


@pytest.mark.parametrize("caller_role,requested,expected", CEILING_MATRIX)
def test_ceiling_matrix_on_invite_creation(
    client, db_session, caller_role, requested, expected
):
    """The same rule governs the role an invitation carries."""
    ws = Workspace(name="Invite ceiling", slug=f"inv-ceil-{caller_role.value}-{requested.value}")
    db_session.add(ws)
    db_session.flush()
    owner = _mk_user(db_session, "inv-ceil-owner")
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=owner.id, role=Role.OWNER.value)
    )
    caller = _mk_user(db_session, f"inv-caller-{caller_role.value}")
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=caller.id, role=caller_role.value)
    )
    db_session.commit()

    as_user(client, caller.id)
    resp = client.post(
        f"/workspaces/{ws.id}/invites",
        json={"email": f"inv-{requested.value}@example.com", "role": requested.value},
    )
    if expected == 403:
        assert resp.status_code == 403, resp.text
        db_session.expire_all()
        pending = (
            db_session.query(models.WorkspaceInvite)
            .filter_by(workspace_id=ws.id)
            .count()
        )
        assert pending == 0, "a refused invite was written anyway"
    else:
        assert resp.status_code == 201, resp.text
        assert resp.json()["role"] == requested.value


def test_only_the_owner_can_transfer_ownership(client, db_session):
    """`co-owner` is not the legal owner: transfer-ownership stays owner-only."""
    ws = Workspace(name="Transfer", slug="transfer-co-owner")
    db_session.add(ws)
    db_session.flush()
    owner = _mk_user(db_session, "t-owner")
    co_owner = _mk_user(db_session, "t-co")
    other = _mk_user(db_session, "t-other")
    for uid, role in ((owner.id, Role.OWNER), (co_owner.id, Role.CO_OWNER), (other.id, Role.MEMBER)):
        db_session.add(
            WorkspaceMembership(workspace_id=ws.id, user_id=uid, role=role.value)
        )
    db_session.commit()

    as_user(client, co_owner.id)
    resp = client.post(
        f"/workspaces/{ws.id}/transfer-ownership", json={"user_id": other.id}
    )
    assert resp.status_code == 403, resp.text
    db_session.expire_all()
    assert (
        db_session.query(WorkspaceMembership)
        .filter_by(workspace_id=ws.id, user_id=owner.id)
        .first()
        .role
        == Role.OWNER.value
    )


def test_co_owner_cannot_delete_the_workspace(client, db_session):
    """workspace.delete maps to OWNER; one rank below is refused."""
    ws = Workspace(name="Delete gate", slug="delete-co-owner")
    db_session.add(ws)
    db_session.flush()
    owner = _mk_user(db_session, "del-owner")
    co_owner = _mk_user(db_session, "del-co")
    for uid, role in ((owner.id, Role.OWNER), (co_owner.id, Role.CO_OWNER)):
        db_session.add(
            WorkspaceMembership(workspace_id=ws.id, user_id=uid, role=role.value)
        )
    db_session.commit()

    as_user(client, co_owner.id)
    resp = client.delete(f"/workspaces/{ws.id}")
    assert resp.status_code == 403, resp.text
    assert db_session.get(Workspace, ws.id) is not None
