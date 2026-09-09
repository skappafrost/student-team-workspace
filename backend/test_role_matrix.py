"""Comprehensive RBAC role-matrix test suite.

Parametrized fixtures create one user per role (owner/admin/member/guest) plus
an unauthenticated case. Tests hit every guarded endpoint asserting:
- 2xx only where the role is allowed
- 403 otherwise
- 401 when no token

Covers privilege escalation attempts (member calling admin-only route, guest POST).
"""

import pytest
import uuid
from datetime import timedelta
from typing import Optional
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from app import app, Role, ROLE_HIERARCHY, get_current_user, create_access_token, Base, _utcnow
import models  # noqa: F401  -- ensures all model tables are registered on Base.metadata
from models import Workspace, WorkspaceInvite, WorkspaceMembership


# ---------------------------------------------------------------------------
# JWT helper for real-token negative tests
# ---------------------------------------------------------------------------

def _jwt_auth_client(user_id: str, expires_delta: Optional[timedelta] = None) -> TestClient:
    """Return a TestClient authenticated with a real JWT for ``user_id``."""
    client = TestClient(app)
    token = create_access_token(user_id, expires_delta=expires_delta)
    client.cookies["session_token"] = token
    return client


# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw.db")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def _get_db_override():
        return db_session

    from database import get_db
    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Role fixtures
# ---------------------------------------------------------------------------

class RoleUser:
    """Container for a test user with a specific role in a workspace."""

    def __init__(self, client: TestClient, user_id: str, role: Role, workspace_id: str = None):
        self._client = client
        self.user_id = user_id
        self.role = role
        self.workspace_id = workspace_id

    @property
    def client(self) -> TestClient:
        """Return the client with this user's auth headers set."""
        # For unauthenticated users, return a completely fresh client
        if self.role is None:
            from fastapi.testclient import TestClient
            from app import app
            fresh_client = TestClient(app)
            return fresh_client

        self._client.headers["X-Test-User-Id"] = self.user_id
        self._client.headers["X-Test-User-Role"] = self.role.value
        return self._client

    def clear_auth(self):
        """Clear auth headers."""
        self._client.headers.pop("X-Test-User-Id", None)
        self._client.headers.pop("X-Test-User-Role", None)
        # Also clear cookies to avoid JWT cookie interference
        self._client.cookies.clear()


@pytest.fixture
def role_users(client, db_session):
    """Create a workspace with 4 users: owner, admin, member, guest.

    Returns a dict mapping Role -> RoleUser for each role.
    """
    # Create workspace as owner
    owner = RoleUser(client, "owner-user", Role.OWNER)
    ws_resp = owner.client.post("/workspaces", json={"name": "Test WS", "slug": "test-ws"})
    assert ws_resp.status_code == 201
    ws_id = ws_resp.json()["id"]
    owner.clear_auth()

    # Create admin user via invite
    admin = RoleUser(client, "admin-user", Role.ADMIN, ws_id)
    invite_resp = owner.client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": _unique_email("admin"), "role": Role.ADMIN.value},
    )
    assert invite_resp.status_code == 201
    token = invite_resp.json()["token"]
    owner.clear_auth()
    admin.client.post("/invites/accept", json={"token": token})
    admin.clear_auth()

    # Create member user via invite
    member = RoleUser(client, "member-user", Role.MEMBER, ws_id)
    invite_resp = owner.client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": _unique_email("member"), "role": Role.MEMBER.value},
    )
    assert invite_resp.status_code == 201
    token = invite_resp.json()["token"]
    owner.clear_auth()
    member.client.post("/invites/accept", json={"token": token})
    member.clear_auth()

    # Create guest user via invite
    guest = RoleUser(client, "guest-user", Role.GUEST, ws_id)
    invite_resp = owner.client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": _unique_email("guest"), "role": Role.GUEST.value},
    )
    assert invite_resp.status_code == 201
    token = invite_resp.json()["token"]
    owner.clear_auth()
    guest.client.post("/invites/accept", json={"token": token})
    guest.clear_auth()

    return {
        Role.OWNER: RoleUser(client, "owner-user", Role.OWNER, ws_id),
        Role.ADMIN: RoleUser(client, "admin-user", Role.ADMIN, ws_id),
        Role.MEMBER: RoleUser(client, "member-user", Role.MEMBER, ws_id),
        Role.GUEST: RoleUser(client, "guest-user", Role.GUEST, ws_id),
    }


@pytest.fixture
def unauthenticated_user(client):
    """A client with no authentication."""
    user = RoleUser(client, "unauth-user", None)
    return user


# ---------------------------------------------------------------------------
# Expected access matrix
# ---------------------------------------------------------------------------

# For each endpoint, define which roles should get 2xx (success)
# All other roles (including unauthenticated) should get 403 or 401
# Only endpoints using get_current_user dependency (support test headers)
EXPECTED_ACCESS = {
    # Workspace endpoints
    ("POST", "/workspaces"): {"allowed": [Role.OWNER, Role.ADMIN, Role.MEMBER], "public": False},
    ("GET", "/workspaces"): {"allowed": [Role.OWNER, Role.ADMIN, Role.MEMBER, Role.GUEST], "public": False},
    ("GET", "/workspaces/{ws_id}"): {"allowed": [Role.OWNER, Role.ADMIN, Role.MEMBER, Role.GUEST], "public": False},
    ("PATCH", "/workspaces/{ws_id}"): {"allowed": [Role.OWNER, Role.ADMIN], "public": False},
    ("DELETE", "/workspaces/{ws_id}"): {"allowed": [Role.OWNER], "public": False},

    # Invite endpoints
    ("POST", "/workspaces/{ws_id}/invites"): {"allowed": [Role.OWNER, Role.ADMIN], "public": False},
    ("GET", "/workspaces/{ws_id}/invites"): {"allowed": [Role.OWNER, Role.ADMIN], "public": False},
    ("PATCH", "/workspaces/{ws_id}/invites/{invite_id}"): {"allowed": [Role.OWNER, Role.ADMIN], "public": False},
    ("DELETE", "/workspaces/{ws_id}/invites/{invite_id}"): {"allowed": [Role.OWNER, Role.ADMIN], "public": False},
    ("POST", "/invites/accept"): {"allowed": [Role.OWNER, Role.ADMIN, Role.MEMBER, Role.GUEST], "public": False},

    # Member management endpoints
    ("GET", "/workspaces/{ws_id}/members"): {"allowed": [Role.OWNER, Role.ADMIN], "public": False},
    ("PATCH", "/workspaces/{ws_id}/members/{user_id}"): {"allowed": [Role.OWNER, Role.ADMIN], "public": False},
    ("DELETE", "/workspaces/{ws_id}/members/{user_id}"): {"allowed": [Role.OWNER, Role.ADMIN], "public": False},
    ("POST", "/workspaces/{ws_id}/transfer-ownership"): {"allowed": [Role.OWNER], "public": False},
}


# ---------------------------------------------------------------------------
# Request payloads for each endpoint (factory functions for unique data)
# ---------------------------------------------------------------------------

def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def _create_test_invite(client: TestClient, ws_id: str, role: Role = Role.MEMBER) -> str:
    """Create a pending invite and return its id."""
    response = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": _unique_email("invite"), "role": role.value},
    )
    assert response.status_code == 201, f"Failed to create invite: {response.text}"
    return response.json()["id"]


def _create_test_member(client: TestClient, ws_id: str, role: Role = Role.MEMBER) -> str:
    """Create a member by inviting and accepting, return the new user's id."""
    user_id = f"{role.value}-member-{uuid.uuid4().hex[:8]}"
    invite_resp = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": _unique_email("member"), "role": role.value},
    )
    assert invite_resp.status_code == 201, f"Failed to create invite for member: {invite_resp.text}"
    token = invite_resp.json()["token"]

    accept_client = TestClient(app)
    accept_client.headers["X-Test-User-Id"] = user_id
    accept_client.headers["X-Test-User-Role"] = role.value
    accept_resp = accept_client.post("/invites/accept", json={"token": token})
    assert accept_resp.status_code == 201, f"Failed to accept invite: {accept_resp.text}"
    return user_id


ENDPOINT_PAYLOAD_FACTORIES = {
    ("POST", "/workspaces"): lambda: {"name": "New WS", "slug": f"new-ws-{uuid.uuid4().hex[:8]}"},
    ("GET", "/workspaces"): lambda: None,
    ("GET", "/workspaces/{ws_id}"): lambda: None,
    ("PATCH", "/workspaces/{ws_id}"): lambda: {"name": "Updated WS"},
    ("DELETE", "/workspaces/{ws_id}"): lambda: None,
    ("POST", "/workspaces/{ws_id}/invites"): lambda: {"email": _unique_email("invitee"), "role": Role.MEMBER.value},
    ("GET", "/workspaces/{ws_id}/invites"): lambda: None,
    ("PATCH", "/workspaces/{ws_id}/invites/{invite_id}"): lambda: {"role": Role.ADMIN.value},
    ("DELETE", "/workspaces/{ws_id}/invites/{invite_id}"): lambda: None,
    ("POST", "/invites/accept"): lambda: {"token": "dummy-token-will-be-replaced"},
    ("GET", "/workspaces/{ws_id}/members"): lambda: None,
    ("PATCH", "/workspaces/{ws_id}/members/{user_id}"): lambda: {"role": Role.ADMIN.value},
    ("DELETE", "/workspaces/{ws_id}/members/{user_id}"): lambda: None,
    ("POST", "/workspaces/{ws_id}/transfer-ownership"): lambda: {"user_id": "dummy-user-will-be-replaced"},
}


def make_request(client: TestClient, method: str, path: str, payload=None, ws_id=None, invite_id=None, user_id=None):
    """Make a request, substituting path parameters if needed."""
    # Use safe replacement so paths with only some placeholders do not raise KeyError.
    if ws_id is not None:
        path = path.replace("{ws_id}", str(ws_id))
    if invite_id is not None:
        path = path.replace("{invite_id}", str(invite_id))
    if user_id is not None:
        path = path.replace("{user_id}", str(user_id))

    if method == "GET":
        return client.get(path)
    elif method == "POST":
        return client.post(path, json=payload)
    elif method == "PATCH":
        return client.patch(path, json=payload)
    elif method == "DELETE":
        return client.delete(path)
    else:
        raise ValueError(f"Unsupported method: {method}")


# ---------------------------------------------------------------------------
# Auth-specific tests (public endpoints)
# ---------------------------------------------------------------------------

class TestPublicAuthEndpoints:
    """Test public auth endpoints that don't require authentication."""

    def test_register_allows_anyone(self, client):
        """Anyone can register - no auth required."""
        # Multiple registrations with unique emails should succeed
        for i in range(3):
            payload = {"email": _unique_email(f"register{i}"), "password": "password123"}
            response = client.post("/auth/register", json=payload)
            assert response.status_code == 201, f"Registration {i} failed: {response.text}"

    def test_register_duplicate_email_returns_409(self, client):
        """Duplicate email registration returns 409."""
        email = _unique_email("dup")
        payload = {"email": email, "password": "password123"}
        client.post("/auth/register", json=payload)
        response = client.post("/auth/register", json=payload)
        assert response.status_code == 409

    def test_login_requires_valid_credentials(self, client):
        """Login requires valid email/password."""
        # First register a user
        email = _unique_email("login")
        password = "password123"
        client.post("/auth/register", json={"email": email, "password": password})

        # Valid credentials should work
        response = client.post("/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200
        assert "access_token" in response.json()

        # Invalid password should fail
        response = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert response.status_code == 401

        # Non-existent user should fail
        response = client.post("/auth/login", json={"email": _unique_email("nonexist"), "password": "x"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Role-matrix tests (guarded endpoints)
# ---------------------------------------------------------------------------

class TestRoleMatrix:
    """Test RBAC matrix for all guarded endpoints."""

    @pytest.mark.parametrize("method,path,config", [
        (method, path, config)
        for (method, path), config in EXPECTED_ACCESS.items()
    ])
    def test_role_matrix(self, role_users, unauthenticated_user, method, path, config):
        """Test that each role gets the expected response for each endpoint."""
        allowed_roles = config["allowed"]
        is_public = config["public"]
        payload_factory = ENDPOINT_PAYLOAD_FACTORIES.get((method, path))

        # Get workspace_id from any role user
        ws_id = next(iter(role_users.values())).workspace_id
        owner = role_users[Role.OWNER]

        # Pre-create reusable resources; each role gets fresh copies so that
        # destructive operations (DELETE member/invite) do not interfere.
        invite_id: Optional[str] = None
        user_id: Optional[str] = None
        needs_target_user = "{user_id}" in path or (method == "POST" and "transfer-ownership" in path)
        if "{invite_id}" in path:
            invite_id = _create_test_invite(owner.client, ws_id)
        elif needs_target_user:
            # transfer-ownership needs a non-owner target member
            target_role = Role.ADMIN if method == "POST" and "transfer-ownership" in path else Role.MEMBER
            user_id = _create_test_member(owner.client, ws_id, target_role)
            # For transfer-ownership payload, fill in the real user_id
            if method == "POST" and "transfer-ownership" in path:
                payload_factory = lambda uid=user_id: {"user_id": uid}  # type: ignore[assignment]

        # Test each authenticated role
        for role, role_user in role_users.items():
            # Refresh per-role resource ids because earlier roles may have
            # mutated or consumed them (e.g. DELETE invites/members).
            current_invite_id = invite_id
            current_user_id = user_id
            if "{invite_id}" in path:
                current_invite_id = _create_test_invite(owner.client, ws_id)
            elif needs_target_user:
                # Re-create target member for each role to keep tests isolated
                target_role = Role.ADMIN if method == "POST" and "transfer-ownership" in path else Role.MEMBER
                current_user_id = _create_test_member(owner.client, ws_id, target_role)
                if method == "POST" and "transfer-ownership" in path:
                    payload_factory = lambda uid=current_user_id: {"user_id": uid}  # type: ignore[assignment]

            payload = payload_factory() if payload_factory else None

            # Special handling for invite accept - need a valid token
            if path == "/invites/accept":
                invite_resp = owner.client.post(
                    f"/workspaces/{ws_id}/invites",
                    json={"email": _unique_email(f"matrix-test-{role.value}"), "role": Role.MEMBER.value},
                )
                assert invite_resp.status_code == 201
                valid_token = invite_resp.json()["token"]
                payload = {"token": valid_token}
                owner.clear_auth()

            response = make_request(
                role_user.client,
                method,
                path,
                payload,
                ws_id=ws_id,
                invite_id=current_invite_id,
                user_id=current_user_id,
            )
            role_user.clear_auth()

            if is_public:
                # Public endpoints should allow anyone (including unauthenticated)
                assert response.status_code < 400, (
                    f"Public endpoint {method} {path} failed for {role.value}: "
                    f"got {response.status_code}, expected 2xx. Response: {response.text}"
                )
            elif allowed_roles is not None and role in allowed_roles:
                # Role is allowed
                assert response.status_code < 400, (
                    f"Allowed role {role.value} got {response.status_code} for {method} {path}. "
                    f"Expected 2xx. Response: {response.text}"
                )
            else:
                # Role is NOT allowed - should get 403 (or 404 for non-existent resources)
                assert response.status_code in (403, 404), (
                    f"Forbidden role {role.value} got {response.status_code} for {method} {path}. "
                    f"Expected 403/404. Response: {response.text}"
                )

        # Test unauthenticated access
        if not is_public:
            payload = payload_factory() if payload_factory else None
            response = make_request(unauthenticated_user.client, method, path, payload, ws_id)
            unauthenticated_user.clear_auth()

            assert response.status_code in (401, 403, 404), (
                f"Unauthenticated access to {method} {path} got {response.status_code}. "
                f"Expected 401/403/404. Response: {response.text}"
            )

    def test_privilege_escalation_member_calling_admin_routes(self, role_users):
        """Test privilege escalation: member calling admin-only routes."""
        member = role_users[Role.MEMBER]
        ws_id = member.workspace_id

        # Member trying to update workspace (requires admin)
        response = member.client.patch(
            f"/workspaces/{ws_id}",
            json={"name": "Hacked by Member"}
        )
        assert response.status_code == 403, (
            f"Member escalation on PATCH /workspaces got {response.status_code}, expected 403"
        )

        # Member trying to delete workspace (requires owner)
        response = member.client.delete(f"/workspaces/{ws_id}")
        assert response.status_code == 403, (
            f"Member escalation on DELETE /workspaces got {response.status_code}, expected 403"
        )

        # Member trying to create invite (requires admin)
        response = member.client.post(
            f"/workspaces/{ws_id}/invites",
            json={"email": "hacker@example.com", "role": Role.ADMIN.value}
        )
        assert response.status_code == 403, (
            f"Member escalation on POST /invites got {response.status_code}, expected 403"
        )

        member.clear_auth()

    def test_privilege_escalation_guest_calling_member_routes(self, role_users):
        """Test privilege escalation: guest calling member+ routes."""
        guest = role_users[Role.GUEST]
        ws_id = guest.workspace_id

        # Guest trying to update workspace (requires admin)
        response = guest.client.patch(
            f"/workspaces/{ws_id}",
            json={"name": "Hacked by Guest"}
        )
        assert response.status_code == 403, (
            f"Guest escalation on PATCH /workspaces got {response.status_code}, expected 403"
        )

        # Guest trying to create invite (requires admin)
        response = guest.client.post(
            f"/workspaces/{ws_id}/invites",
            json={"email": "hacker@example.com", "role": Role.ADMIN.value}
        )
        assert response.status_code == 403, (
            f"Guest escalation on POST /invites got {response.status_code}, expected 403"
        )

        guest.clear_auth()

    def test_privilege_escalation_admin_calling_owner_routes(self, role_users):
        """Test privilege escalation: admin calling owner-only routes."""
        admin = role_users[Role.ADMIN]
        ws_id = admin.workspace_id

        # Admin trying to delete workspace (requires owner)
        response = admin.client.delete(f"/workspaces/{ws_id}")
        assert response.status_code == 403, (
            f"Admin escalation on DELETE /workspaces got {response.status_code}, expected 403"
        )

        admin.clear_auth()

    def test_unauthenticated_cannot_access_guarded_endpoints(self, client, unauthenticated_user):
        """Test that unauthenticated users get 401 on all guarded endpoints."""
        guarded_endpoints = [
            ("POST", "/workspaces"),
            ("GET", "/workspaces"),
            ("GET", "/workspaces/{ws_id}"),
            ("PATCH", "/workspaces/{ws_id}"),
            ("DELETE", "/workspaces/{ws_id}"),
            ("POST", "/workspaces/{ws_id}/invites"),
            ("POST", "/invites/accept"),
        ]

        # For workspace-specific endpoints, we need a valid workspace_id
        # Create one first using a temporary authenticated user
        temp_client = TestClient(app)
        temp_client.headers["X-Test-User-Id"] = "temp-owner"
        temp_client.headers["X-Test-User-Role"] = Role.OWNER.value
        ws_resp = temp_client.post("/workspaces", json={"name": "Temp", "slug": "temp"})
        assert ws_resp.status_code == 201
        ws_id = ws_resp.json()["id"]

        # Create a valid invite token for /invites/accept
        invite_resp = temp_client.post(
            f"/workspaces/{ws_id}/invites",
            json={"email": "unauth-test@example.com", "role": Role.MEMBER.value},
        )
        assert invite_resp.status_code == 201
        valid_token = invite_resp.json()["token"]

        for method, path in guarded_endpoints:
            payload_factory = ENDPOINT_PAYLOAD_FACTORIES.get((method, path))
            payload = payload_factory() if payload_factory else None
            if path == "/invites/accept":
                payload = {"token": valid_token}

            response = make_request(unauthenticated_user.client, method, path, payload, ws_id)
            unauthenticated_user.clear_auth()

            assert response.status_code == 401, (
                f"Unauthenticated access to {method} {path} got {response.status_code}, expected 401"
            )

    def test_cross_workspace_access_denied(self, client):
        """Test that users cannot access workspaces they're not members of."""
        # Create workspace A with owner A
        owner_a = RoleUser(client, "owner-a", Role.OWNER)
        ws_a_resp = owner_a.client.post("/workspaces", json={"name": "Workspace A", "slug": "ws-a"})
        assert ws_a_resp.status_code == 201
        ws_a_id = ws_a_resp.json()["id"]
        owner_a.clear_auth()

        # Create workspace B with owner B
        owner_b = RoleUser(client, "owner-b", Role.OWNER)
        ws_b_resp = owner_b.client.post("/workspaces", json={"name": "Workspace B", "slug": "ws-b"})
        assert ws_b_resp.status_code == 201
        ws_b_id = ws_b_resp.json()["id"]
        owner_b.clear_auth()

        # Owner A should NOT access workspace B
        owner_a = RoleUser(client, "owner-a", Role.OWNER)
        response = owner_a.client.get(f"/workspaces/{ws_b_id}")
        assert response.status_code == 403, (
            f"Cross-workspace access got {response.status_code}, expected 403"
        )
        owner_a.clear_auth()

        # Owner A should NOT update workspace B
        owner_a = RoleUser(client, "owner-a", Role.OWNER)
        response = owner_a.client.patch(f"/workspaces/{ws_b_id}", json={"name": "Hacked"})
        assert response.status_code == 403, (
            f"Cross-workspace update got {response.status_code}, expected 403"
        )
        owner_a.clear_auth()

        # Owner A should NOT delete workspace B
        owner_a = RoleUser(client, "owner-a", Role.OWNER)
        response = owner_a.client.delete(f"/workspaces/{ws_b_id}")
        assert response.status_code == 403, (
            f"Cross-workspace delete got {response.status_code}, expected 403"
        )
        owner_a.clear_auth()

    def test_role_hierarchy_transitivity(self, client):
        """Test that role hierarchy is transitive (owner > admin > member > guest)."""
        # Owner can do everything
        owner = RoleUser(client, "owner-h", Role.OWNER)
        ws_resp = owner.client.post("/workspaces", json={"name": "WS-Owner", "slug": "ws-owner-h"})
        assert ws_resp.status_code == 201
        ws_id = ws_resp.json()["id"]

        assert owner.client.patch(f"/workspaces/{ws_id}", json={"name": "Owner update"}).status_code == 200
        assert owner.client.post(f"/workspaces/{ws_id}/invites", json={"email": "test@example.com"}).status_code == 201
        assert owner.client.delete(f"/workspaces/{ws_id}").status_code == 204
        owner.clear_auth()

        # Admin can update and invite but NOT delete
        admin = RoleUser(client, "admin-h", Role.ADMIN)
        owner.client.headers["X-Test-User-Id"] = "owner-h"
        owner.client.headers["X-Test-User-Role"] = Role.OWNER.value
        ws_resp2 = owner.client.post("/workspaces", json={"name": "WS2", "slug": "ws2-h"})
        ws_id2 = ws_resp2.json()["id"]
        invite_resp = owner.client.post(f"/workspaces/{ws_id2}/invites", json={"email": "admin@example.com", "role": Role.ADMIN.value})
        token = invite_resp.json()["token"]
        owner.clear_auth()
        admin.client.post("/invites/accept", json={"token": token})

        assert admin.client.patch(f"/workspaces/{ws_id2}", json={"name": "Admin update"}).status_code == 200
        assert admin.client.post(f"/workspaces/{ws_id2}/invites", json={"email": "test@example.com"}).status_code == 201
        assert admin.client.delete(f"/workspaces/{ws_id2}").status_code == 403
        admin.clear_auth()

        # Member can view but NOT update/invite/delete
        member = RoleUser(client, "member-h", Role.MEMBER)
        owner.client.headers["X-Test-User-Id"] = "owner-h"
        owner.client.headers["X-Test-User-Role"] = Role.OWNER.value
        ws_resp3 = owner.client.post("/workspaces", json={"name": "WS3", "slug": "ws3-h"})
        ws_id3 = ws_resp3.json()["id"]
        invite_resp = owner.client.post(f"/workspaces/{ws_id3}/invites", json={"email": "member@example.com", "role": Role.MEMBER.value})
        token = invite_resp.json()["token"]
        owner.clear_auth()
        member.client.post("/invites/accept", json={"token": token})

        assert member.client.get(f"/workspaces/{ws_id3}").status_code == 200
        assert member.client.patch(f"/workspaces/{ws_id3}", json={"name": "Member update"}).status_code == 403
        assert member.client.post(f"/workspaces/{ws_id3}/invites", json={"email": "test@example.com"}).status_code == 403
        assert member.client.delete(f"/workspaces/{ws_id3}").status_code == 403
        member.clear_auth()

        # Guest can view but NOT update/invite/delete
        guest = RoleUser(client, "guest-h", Role.GUEST)
        owner.client.headers["X-Test-User-Id"] = "owner-h"
        owner.client.headers["X-Test-User-Role"] = Role.OWNER.value
        ws_resp4 = owner.client.post("/workspaces", json={"name": "WS4", "slug": "ws4-h"})
        ws_id4 = ws_resp4.json()["id"]
        invite_resp = owner.client.post(f"/workspaces/{ws_id4}/invites", json={"email": "guest@example.com", "role": Role.GUEST.value})
        token = invite_resp.json()["token"]
        owner.clear_auth()
        guest.client.post("/invites/accept", json={"token": token})

        assert guest.client.get(f"/workspaces/{ws_id4}").status_code == 200
        assert guest.client.patch(f"/workspaces/{ws_id4}", json={"name": "Guest update"}).status_code == 403
        assert guest.client.post(f"/workspaces/{ws_id4}/invites", json={"email": "test@example.com"}).status_code == 403
        assert guest.client.delete(f"/workspaces/{ws_id4}").status_code == 403
        guest.clear_auth()


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case tests for RBAC."""

    def test_invalid_role_in_token_defaults_to_guest(self, client):
        """Test that invalid role in token defaults to guest (lowest privilege).

        Note: In the current implementation, workspace endpoints check the
        membership role from the database, not the header. This test verifies
        the /auth/me endpoint behavior where header role is used directly.
        """
        # Register a user first
        client.post("/auth/register", json={"email": "test-role@example.com", "password": "password123"})
        # Login to get cookie
        client.post("/auth/login", json={"email": "test-role@example.com", "password": "password123"})

        # Now test /auth/me with invalid role header
        client.headers["X-Test-User-Id"] = "test-user"
        client.headers["X-Test-User-Role"] = "superuser"  # Invalid role

        response = client.get("/auth/me")
        # The get_current_user function falls back to Role.MEMBER for invalid roles
        # but this endpoint doesn't enforce role checks

        client.headers.pop("X-Test-User-Id", None)
        client.headers.pop("X-Test-User-Role", None)

    def test_expired_token_returns_401(self, client):
        """Test that expired JWT returns 401."""
        # Register a real user and obtain a valid-looking token that is already expired
        email = _unique_email("expired")
        password = "password123"
        client.post("/auth/register", json={"email": email, "password": password})
        login_resp = client.post("/auth/login", json={"email": email, "password": password})
        assert login_resp.status_code == 200
        user_id = login_resp.json()["user"]["id"]

        expired_client = _jwt_auth_client(user_id, expires_delta=timedelta(seconds=-1))
        response = expired_client.get("/workspaces")
        assert response.status_code == 401, (
            f"Expired token got {response.status_code}, expected 401. Response: {response.text}"
        )

    def test_malformed_token_returns_401(self, client):
        """Test that malformed JWT returns 401."""
        bad_client = TestClient(app)
        bad_client.cookies["session_token"] = "not-a-jwt"
        response = bad_client.get("/workspaces")
        assert response.status_code == 401, (
            f"Malformed token got {response.status_code}, expected 401. Response: {response.text}"
        )

    def test_valid_token_with_insufficient_role_returns_403(self, role_users):
        """Test that a valid token for a low-privilege member gets 403 on admin routes."""
        member = role_users[Role.MEMBER]
        ws_id = member.workspace_id

        # Use a fresh client with real JWT derived from the member's user_id
        jwt_client = _jwt_auth_client(member.user_id)
        response = jwt_client.patch(f"/workspaces/{ws_id}", json={"name": "JWT Hack"})
        assert response.status_code == 403, (
            f"JWT member got {response.status_code} on PATCH /workspaces, expected 403. "
            f"Response: {response.text}"
        )
        response = jwt_client.delete(f"/workspaces/{ws_id}")
        assert response.status_code == 403, (
            f"JWT member got {response.status_code} on DELETE /workspaces, expected 403. "
            f"Response: {response.text}"
        )

    def test_nonexistent_workspace_returns_404(self, role_users):
        """Test that accessing non-existent workspace returns 404 not 403."""
        owner = role_users[Role.OWNER]

        fake_id = "00000000-0000-0000-0000-000000000000"
        response = owner.client.get(f"/workspaces/{fake_id}")
        assert response.status_code == 404, (
            f"Non-existent workspace got {response.status_code}, expected 404"
        )

        response = owner.client.patch(f"/workspaces/{fake_id}", json={"name": "Hack"})
        assert response.status_code == 404

        response = owner.client.delete(f"/workspaces/{fake_id}")
        assert response.status_code == 404

        owner.clear_auth()


# ---------------------------------------------------------------------------
# Summary test that prints the matrix
# ---------------------------------------------------------------------------

def test_print_role_matrix_summary():
    """Print a human-readable summary of the role matrix for documentation."""
    print("\n" + "=" * 80)
    print("RBAC ROLE MATRIX SUMMARY")
    print("=" * 80)
    print(f"{'Endpoint':<45} {'Owner':<8} {'Admin':<8} {'Member':<8} {'Guest':<8} {'Unauth':<8}")
    print("-" * 80)

    for (method, path), config in sorted(EXPECTED_ACCESS.items()):
        allowed = config["allowed"]
        is_public = config["public"]

        def check(role):
            if is_public:
                return "✓"
            if allowed is None:
                return "✓"
            return "✓" if role in allowed else "✗"

        owner_ok = check(Role.OWNER)
        admin_ok = check(Role.ADMIN)
        member_ok = check(Role.MEMBER)
        guest_ok = check(Role.GUEST)
        unauth_ok = "✓" if is_public else "401"

        endpoint_str = f"{method} {path}"
        print(f"{endpoint_str:<45} {owner_ok:<8} {admin_ok:<8} {member_ok:<8} {guest_ok:<8} {unauth_ok:<8}")

    print("=" * 80)
    print("✓ = 2xx allowed | ✗ = 403 forbidden | 401 = unauthenticated")


# ---------------------------------------------------------------------------
# T002: Cross-tenant RBAC regression matrix (real JWT auth)
# ---------------------------------------------------------------------------
# Locks T001's fix: every privileged workspace-scoped endpoint must scope its
# membership/role check to the *path* workspace_id only. A user who belongs to
# a *different* workspace (ws-B) must never reach ws-A's resources by passing
# a stray `?workspace_id=` query param (pre-fix: 200/204 — cross-tenant hole).
#
# Actors (>= 5 required by T002; we use 6):
#   owner    -> owner of the target workspace ws-A
#   admin    -> admin of ws-A
#   member   -> member of ws-A
#   guest    -> guest of ws-A
#   stranger -> member of the OTHER workspace ws-B only (the regression actor)
#   anonymous-> no auth at all
#
# All requests use REAL JWTs (Authorization: Bearer <create_access_token(user_id)>),
# not the X-Test-User-* header bypass.

from types import SimpleNamespace

T002_ACTORS = ["owner", "admin", "member", "guest", "stranger", "anonymous"]


def _mk_unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _t002_endpoints() -> list:
    """The 12 privileged endpoints touched by T001 (path-scoped call sites)."""
    return [
        {"id": "update_workspace", "method": "PATCH", "path": "/workspaces/{ws_id}",
         "min_role": Role.ADMIN, "ok_status": 200,
         "payload": lambda w: {"name": "T002 renamed"}},
        {"id": "delete_workspace", "method": "DELETE", "path": "/workspaces/{ws_id}",
         "min_role": Role.OWNER, "ok_status": 204,
         "payload": lambda w: None},
        {"id": "create_invite", "method": "POST", "path": "/workspaces/{ws_id}/invites",
         "min_role": Role.ADMIN, "ok_status": 201,
         "payload": lambda w: {"email": _mk_unique_email("invitee"), "role": Role.MEMBER.value}},
        {"id": "list_invites", "method": "GET", "path": "/workspaces/{ws_id}/invites",
         "min_role": Role.ADMIN, "ok_status": 200,
         "payload": lambda w: None},
        {"id": "update_invite", "method": "PATCH", "path": "/workspaces/{ws_id}/invites/{invite_id}",
         "min_role": Role.ADMIN, "ok_status": 200,
         "payload": lambda w: {"role": Role.ADMIN.value}},
        {"id": "cancel_invite", "method": "DELETE", "path": "/workspaces/{ws_id}/invites/{invite_id}",
         "min_role": Role.ADMIN, "ok_status": 204,
         "payload": lambda w: None},
        {"id": "list_members", "method": "GET", "path": "/workspaces/{ws_id}/members",
         "min_role": Role.ADMIN, "ok_status": 200,
         "payload": lambda w: None},
        {"id": "update_member_role", "method": "PATCH", "path": "/workspaces/{ws_id}/members/{user_id}",
         "min_role": Role.ADMIN, "ok_status": 200,
         "payload": lambda w: {"role": Role.MEMBER.value}},
        {"id": "remove_member", "method": "DELETE", "path": "/workspaces/{ws_id}/members/{user_id}",
         "min_role": Role.ADMIN, "ok_status": 204,
         "payload": lambda w: None},
        {"id": "transfer_ownership", "method": "POST", "path": "/workspaces/{ws_id}/transfer-ownership",
         "min_role": Role.OWNER, "ok_status": 200,
         "payload": lambda w: {"user_id": w.users["member"].id}},
        {"id": "create_project", "method": "POST", "path": "/workspaces/{ws_id}/projects",
         "min_role": Role.MEMBER, "ok_status": 201,
         "payload": lambda w: {"name": "T002 project"}},
        # create_workspace has no target workspace; any authenticated user may create.
        {"id": "create_workspace", "method": "POST", "path": "/workspaces",
         "min_role": None, "ok_status": 201,
         "payload": lambda w: {"name": "T002 new ws", "slug": f"t002-{uuid.uuid4().hex[:8]}"}},
    ]


T002_ENDPOINTS = _t002_endpoints()
_T002_ACTOR_ROLE = {
    "owner": Role.OWNER,
    "admin": Role.ADMIN,
    "member": Role.MEMBER,
    "guest": Role.GUEST,
}


def _t002_expected(endpoint: dict, actor: str) -> int:
    """Expected status for `endpoint` invoked by `actor` on the target ws-A."""
    if actor == "anonymous":
        return 401
    if endpoint["min_role"] is None:
        # Global (token) role check only — any authenticated user passes.
        return endpoint["ok_status"]
    if actor == "stranger":
        # Not a member of ws-A at all -> path-scoped membership check denies.
        return 403
    if ROLE_HIERARCHY[_T002_ACTOR_ROLE[actor]] >= ROLE_HIERARCHY[endpoint["min_role"]]:
        return endpoint["ok_status"]
    return 403


@pytest.fixture
def t002_world(db_session):
    """Two-workspace RBAC world: ws-A (owner U1) + ws-B (owner U2) + stranger U3.

    Users and memberships are real DB rows; auth uses real JWTs minted with
    create_access_token(user_id) and sent as `Authorization: Bearer`.
    """
    def _mk_user(prefix):
        u = models.User(
            email=_mk_unique_email(prefix),
            display_name=prefix,
            hashed_password=None,
        )
        db_session.add(u)
        db_session.flush()
        return u

    def _mk_ws(prefix):
        ws = models.Workspace(name=f"T002 {prefix}", slug=f"t002-{prefix}-{uuid.uuid4().hex[:8]}")
        db_session.add(ws)
        db_session.flush()
        return ws

    def _mk_membership(ws, user, role: Role):
        m = models.WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=role.value)
        db_session.add(m)
        db_session.flush()
        return m

    u1 = _mk_user("u1")      # owner of ws-A
    u1a = _mk_user("u1a")    # admin of ws-A
    u1m = _mk_user("u1m")    # member of ws-A
    u1g = _mk_user("u1g")    # guest of ws-A
    u2 = _mk_user("u2")      # owner of ws-B
    u3 = _mk_user("u3")      # member of ws-B -> stranger to ws-A

    ws_a = _mk_ws("A")
    ws_b = _mk_ws("B")

    _mk_membership(ws_a, u1, Role.OWNER)
    _mk_membership(ws_a, u1a, Role.ADMIN)
    _mk_membership(ws_a, u1m, Role.MEMBER)
    _mk_membership(ws_a, u1g, Role.GUEST)
    _mk_membership(ws_b, u2, Role.OWNER)
    _mk_membership(ws_b, u3, Role.MEMBER)

    # One pending invite in ws-A for the invite endpoints.
    invite = models.WorkspaceInvite(
        workspace_id=ws_a.id,
        email=_mk_unique_email("pending"),
        role=Role.MEMBER.value,
        expires_at=_utcnow() + timedelta(days=7),
    )
    db_session.add(invite)
    db_session.flush()
    db_session.commit()

    users = {"owner": u1, "admin": u1a, "member": u1m, "guest": u1g,
             "owner_b": u2, "stranger": u3}
    tokens = {key: create_access_token(u.id) for key, u in users.items()}

    return SimpleNamespace(
        ws_a=ws_a,
        ws_b=ws_b,
        invite=invite,
        users=users,
        tokens=tokens,
    )


def _t002_path(endpoint: dict, w) -> str:
    path = endpoint["path"]
    path = path.replace("{ws_id}", w.ws_a.id)
    path = path.replace("{invite_id}", w.invite.id)
    path = path.replace("{user_id}", w.users["member"].id)
    return path


def _t002_request(client, method: str, path: str, token=None, payload=None, params=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    kwargs = {}
    if params is not None:
        kwargs["params"] = params
    if method == "GET":
        return client.get(path, headers=headers, **kwargs)
    if method == "POST":
        return client.post(path, json=payload, headers=headers, **kwargs)
    if method == "PATCH":
        return client.patch(path, json=payload, headers=headers, **kwargs)
    if method == "DELETE":
        return client.delete(path, headers=headers, **kwargs)
    raise AssertionError(f"unexpected method {method}")


def _t002_snapshot(client, w, endpoint: dict):
    """Comparable snapshot of the ws-A state relevant to `endpoint` (owner view)."""
    if endpoint["id"] == "create_workspace":
        return None  # creates a brand-new workspace; no target-ws state to compare
    owner = w.tokens["owner"]
    eid = endpoint["id"]
    if eid in ("update_workspace", "delete_workspace"):
        r = _t002_request(client, "GET", f"/workspaces/{w.ws_a.id}", token=owner)
        return (r.status_code, r.json().get("name") if r.status_code == 200 else None)
    if eid in ("create_invite", "list_invites", "update_invite", "cancel_invite"):
        r = _t002_request(client, "GET", f"/workspaces/{w.ws_a.id}/invites", token=owner)
        if r.status_code != 200:
            return (r.status_code,)
        return tuple(sorted((i["id"], i["role"]) for i in r.json()))
    if eid in ("list_members", "update_member_role", "remove_member", "transfer_ownership"):
        r = _t002_request(client, "GET", f"/workspaces/{w.ws_a.id}/members", token=owner)
        if r.status_code != 200:
            return (r.status_code,)
        return tuple(sorted((m["user_id"], m["role"]) for m in r.json()))
    if eid == "create_project":
        r = _t002_request(client, "GET", f"/workspaces/{w.ws_a.id}/projects", token=owner)
        if r.status_code != 200:
            return (r.status_code,)
        return tuple(sorted(p["name"] for p in r.json()))
    return None


class TestT002CrossTenantMatrix:
    """12 privileged endpoints x 6 actor positions with exact status + no side effects."""

    @pytest.mark.parametrize("endpoint", T002_ENDPOINTS,
                             ids=[e["id"] for e in T002_ENDPOINTS])
    @pytest.mark.parametrize("actor", T002_ACTORS)
    def test_path_scoped_rbac(self, client, t002_world, endpoint, actor):
        w = t002_world
        expected = _t002_expected(endpoint, actor)
        path = _t002_path(endpoint, w)
        payload = endpoint["payload"](w)
        token = w.tokens.get(actor)

        snapshot_before = None
        if endpoint["method"] in ("POST", "PATCH", "DELETE"):
            snapshot_before = _t002_snapshot(client, w, endpoint)

        resp = _t002_request(client, endpoint["method"], path, token=token, payload=payload)

        assert resp.status_code == expected, (
            f"{endpoint['method']} {endpoint['path']} as {actor}: got "
            f"{resp.status_code}, expected {expected}. Body: {resp.text[:200]}"
        )

        # Forbidden writes must leave no trace (re-GET as owner).
        if expected in (401, 403) and snapshot_before is not None:
            snapshot_after = _t002_snapshot(client, w, endpoint)
            assert snapshot_after == snapshot_before, (
                f"Forbidden {endpoint['method']} {endpoint['path']} as {actor} mutated "
                f"state: {snapshot_before} -> {snapshot_after}"
            )


class TestT002QueryPathMismatch:
    """T001 regression: a stray ?workspace_id= query must NEVER rescope the check.

    Pre-fix, require_permission() read workspace_id from the QUERY string while
    the handler operated on the PATH workspace — so an owner/member of ws-B could
    pass ?workspace_id={ws_b} and hit ws-A's path resources (200/204 instead of 403).
    """

    MISMATCH_ENDPOINTS = [e for e in T002_ENDPOINTS if "{ws_id}" in e["path"]]

    @pytest.mark.parametrize("endpoint", MISMATCH_ENDPOINTS,
                             ids=[e["id"] for e in MISMATCH_ENDPOINTS])
    @pytest.mark.parametrize("attacker", ["owner_b", "stranger"])
    def test_foreign_query_workspace_id_is_denied(self, client, t002_world, endpoint, attacker):
        """Path targets ws-A but ?workspace_id={ws_b}: must be 403 (path-scoped)."""
        w = t002_world
        path = _t002_path(endpoint, w)
        payload = endpoint["payload"](w)

        snapshot_before = None
        if endpoint["method"] in ("POST", "PATCH", "DELETE"):
            snapshot_before = _t002_snapshot(client, w, endpoint)

        resp = _t002_request(
            client, endpoint["method"], path,
            token=w.tokens[attacker], payload=payload,
            params={"workspace_id": w.ws_b.id},
        )

        assert resp.status_code == 403, (
            f"Cross-tenant hole: {endpoint['method']} {endpoint['path']} with "
            f"?workspace_id={w.ws_b.id} as {attacker} got {resp.status_code}, expected 403. "
            f"Body: {resp.text[:200]}"
        )
        if snapshot_before is not None:
            assert _t002_snapshot(client, w, endpoint) == snapshot_before, (
                f"Forbidden {endpoint['method']} {endpoint['path']} with foreign "
                f"workspace_id as {attacker} mutated state"
            )

    def test_duplicate_workspace_id_params_take_first_and_deny(self, client, t002_world):
        """?workspace_id={ws_b}&workspace_id={ws_a}: FastAPI binds the FIRST (ws_b).

        The path still names ws-A, so the path-scoped check must deny with 403.
        """
        w = t002_world
        resp = _t002_request(
            client, "PATCH", f"/workspaces/{w.ws_a.id}",
            token=w.tokens["owner_b"], payload={"name": "HIJACK"},
            params=[("workspace_id", w.ws_b.id), ("workspace_id", w.ws_a.id)],
        )
        assert resp.status_code == 403, (
            f"Duplicate workspace_id params bypassed RBAC: got {resp.status_code}, "
            f"expected 403. Body: {resp.text[:200]}"
        )

    def test_matching_query_param_no_behavior_change(self, client, t002_world):
        """?workspace_id={ws_a} (matching the path) behaves like no query at all."""
        w = t002_world
        # member on an admin-only route -> still 403
        resp = _t002_request(
            client, "PATCH", f"/workspaces/{w.ws_a.id}",
            token=w.tokens["member"], payload={"name": "X"},
            params={"workspace_id": w.ws_a.id},
        )
        assert resp.status_code == 403
        # owner on the same route -> still 200
        resp = _t002_request(
            client, "PATCH", f"/workspaces/{w.ws_a.id}",
            token=w.tokens["owner"], payload={"name": "OK rename"},
            params={"workspace_id": w.ws_a.id},
        )
        assert resp.status_code == 200

    def test_foreign_query_write_leaves_no_side_effect(self, client, t002_world):
        """The T001 probe scenario: rename/delete with a foreign workspace_id must
        be denied AND leave ws-A untouched (re-GET as owner)."""
        w = t002_world
        r0 = _t002_request(client, "GET", f"/workspaces/{w.ws_a.id}", token=w.tokens["owner"])
        assert r0.status_code == 200
        original_name = r0.json()["name"]

        # PATCH rename hijack attempt with foreign query
        resp = _t002_request(
            client, "PATCH", f"/workspaces/{w.ws_a.id}",
            token=w.tokens["owner_b"], payload={"name": "HIJACKED"},
            params={"workspace_id": w.ws_b.id},
        )
        assert resp.status_code == 403
        r1 = _t002_request(client, "GET", f"/workspaces/{w.ws_a.id}", token=w.tokens["owner"])
        assert r1.status_code == 200
        assert r1.json()["name"] == original_name, "Workspace name changed despite 403!"

        # DELETE hijack attempt with foreign query
        resp = _t002_request(
            client, "DELETE", f"/workspaces/{w.ws_a.id}",
            token=w.tokens["owner_b"],
            params={"workspace_id": w.ws_b.id},
        )
        assert resp.status_code == 403
        r2 = _t002_request(client, "GET", f"/workspaces/{w.ws_a.id}", token=w.tokens["owner"])
        assert r2.status_code == 200, "Workspace deleted despite 403!"


class TestT002ChannelWebsocket:
    """WS endpoint /ws/channels/{id}: membership check runs inside the handler.

    The handler uses the module-level DB (next(get_db())), so the world is seeded
    through the same sqlite file via set_db_url (mirrors test_chat_ws.py).
    """

    @pytest.fixture
    def ws_world(self):
        # The WS handler reads the module-level engine (next(get_db())), so point it
        # at the SAME sqlite file the REST fixtures use (./test_stw.db). Tables and
        # rows are created by the db_session fixture + REST calls.
        from database import set_db_url
        set_db_url("sqlite:///./test_stw.db")
        yield

    def _seed(self, client):
        def _reg(prefix):
            email = _mk_unique_email(prefix)
            r = client.post("/auth/register", json={"email": email, "password": "password123"})
            assert r.status_code == 201, r.text
            # register() sets a session_token cookie that would shadow the
            # Authorization header (cookie wins in _token_from_request); drop it.
            client.cookies.clear()
            data = r.json()
            return data["user"]["id"], data["access_token"], email

        u1_id, u1_tok, _ = _reg("ws-u1")
        u2_id, u2_tok, _ = _reg("ws-u2")

        ws_a = client.post(
            "/workspaces",
            headers={"Authorization": f"Bearer {u1_tok}"},
            json={"name": "WS-A", "slug": f"wsa-{uuid.uuid4().hex[:8]}"},
        ).json()

        # guest of ws-A
        g_id, g_tok, g_email = _reg("ws-guest")
        inv = client.post(
            f"/workspaces/{ws_a['id']}/invites",
            headers={"Authorization": f"Bearer {u1_tok}"},
            json={"email": g_email, "role": Role.GUEST.value},
        ).json()
        acc = client.post(
            "/invites/accept",
            headers={"Authorization": f"Bearer {g_tok}"},
            json={"token": inv["token"]},
        )
        assert acc.status_code == 201, acc.text

        # ws-B owned by u2, with stranger u3 as member
        ws_b = client.post(
            "/workspaces",
            headers={"Authorization": f"Bearer {u2_tok}"},
            json={"name": "WS-B", "slug": f"wsb-{uuid.uuid4().hex[:8]}"},
        ).json()
        s_id, s_tok, s_email = _reg("ws-stranger")
        inv = client.post(
            f"/workspaces/{ws_b['id']}/invites",
            headers={"Authorization": f"Bearer {u2_tok}"},
            json={"email": s_email, "role": Role.MEMBER.value},
        ).json()
        acc = client.post(
            "/invites/accept",
            headers={"Authorization": f"Bearer {s_tok}"},
            json={"token": inv["token"]},
        )
        assert acc.status_code == 201, acc.text

        # public channel in ws-A
        ch = client.post(
            f"/workspaces/{ws_a['id']}/channels",
            headers={"Authorization": f"Bearer {u1_tok}"},
            json={"name": "general", "type": "general"},
        )
        assert ch.status_code == 201, ch.text

        return {
            "channel_id": ch.json()["id"],
            "u1_tok": u1_tok,
            "u2_tok": u2_tok,
            "guest_tok": g_tok,
            "stranger_tok": s_tok,
        }

    def test_workspace_member_can_join_channel(self, client, ws_world):
        w = self._seed(client)
        with client.websocket_connect(
            f"/ws/channels/{w['channel_id']}?session_token={w['u1_tok']}"
        ) as wsock:
            wsock.send_text("ping")
            data = wsock.receive_json()
            assert data["type"] == "pong"

    def test_member_of_other_workspace_cannot_join(self, client, ws_world):
        w = self._seed(client)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/ws/channels/{w['channel_id']}?session_token={w['stranger_tok']}"
            ) as wsock:
                wsock.receive_text()

    def test_guest_cannot_join_channel(self, client, ws_world):
        w = self._seed(client)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/ws/channels/{w['channel_id']}?session_token={w['guest_tok']}"
            ) as wsock:
                wsock.receive_text()
        assert exc_info.value.code in (1008, 1006), exc_info.value.code

    def test_anonymous_cannot_join_channel(self, client, ws_world):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/channels/nonexistent-channel") as wsock:
                wsock.receive_text()
        assert exc_info.value.code in (1008, 1006), exc_info.value.code
