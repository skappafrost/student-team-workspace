import datetime

import pytest
from fastapi.testclient import TestClient

from app import app, Role, _utcnow
from conftest import as_user, clear_auth
from models import Workspace, WorkspaceInvite, WorkspaceMembership


# ---------------------------------------------------------------------------
# Auth helpers (shared, real-JWT based — see conftest.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Workspace CRUD tests
# ---------------------------------------------------------------------------

def test_create_workspace(client):
    as_user(client, "alice")
    response = client.post(
        "/workspaces",
        json={"name": "Science Club", "slug": "science-club", "description": "Team workspace"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Science Club"
    assert data["slug"] == "science-club"
    assert data["description"] == "Team workspace"
    assert len(data["memberships"]) == 1
    assert data["memberships"][0]["role"] == Role.OWNER.value


def test_create_workspace_duplicate_slug(client):
    as_user(client, "alice")
    client.post(
        "/workspaces",
        json={"name": "Science Club", "slug": "science-club"},
    )
    response = client.post(
        "/workspaces",
        json={"name": "Other", "slug": "science-club"},
    )
    assert response.status_code == 409


def test_list_workspaces_only_shows_memberships(client):
    as_user(client, "alice")
    r1 = client.post("/workspaces", json={"name": "WS1", "slug": "ws1"})
    assert r1.status_code == 201

    as_user(client, "bob")
    r2 = client.post("/workspaces", json={"name": "WS2", "slug": "ws2"})
    assert r2.status_code == 201

    # Alice should only see WS1
    as_user(client, "alice")
    response = client.get("/workspaces")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["slug"] == "ws1"


def test_get_workspace_forbidden_for_non_member(client):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Private", "slug": "private"})
    ws_id = ws.json()["id"]

    as_user(client, "bob")
    response = client.get(f"/workspaces/{ws_id}")
    assert response.status_code == 403


def test_update_workspace(client):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Old", "slug": "old"})
    ws_id = ws.json()["id"]

    response = client.patch(f"/workspaces/{ws_id}", json={"name": "New"})
    assert response.status_code == 200
    assert response.json()["name"] == "New"


def test_update_workspace_forbidden_for_member_role(client):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Org", "slug": "org"})
    ws_id = ws.json()["id"]

    # Add Bob as member
    invite_resp = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.MEMBER.value},
    )
    token = invite_resp.json()["token"]

    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Bob (member) should not update
    response = client.patch(f"/workspaces/{ws_id}", json={"name": "Hacked"})
    assert response.status_code == 403


def test_delete_workspace_requires_owner(client):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Del", "slug": "del"})
    ws_id = ws.json()["id"]

    # Create invite, accept as bob to make bob admin
    as_user(client, "alice")  # still alice
    invite_resp = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.ADMIN.value},
    )
    token = invite_resp.json()["token"]

    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Admin cannot delete
    response = client.delete(f"/workspaces/{ws_id}")
    assert response.status_code == 403

    # Owner can delete
    as_user(client, "alice")
    response = client.delete(f"/workspaces/{ws_id}")
    assert response.status_code == 204


def test_delete_nonexistent_workspace_returns_404(client):
    as_user(client, "alice")
    response = client.delete("/workspaces/nonexistent-uuid")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Invite tests
# ---------------------------------------------------------------------------

def test_create_invite_logs_and_returns_token(client, caplog):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Invite", "slug": "invite"})
    ws_id = ws.json()["id"]

    with caplog.at_level("INFO"):
        response = client.post(
            f"/workspaces/{ws_id}/invites",
            json={"email": "bob@example.com", "role": Role.MEMBER.value},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "bob@example.com"
    assert data["role"] == Role.MEMBER.value
    assert data["workspace_id"] == ws_id
    assert "send_invite_email" in caplog.text or "bob@example.com" in caplog.text


def test_invite_create_forbidden_for_member(client):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Org", "slug": "org2"})
    ws_id = ws.json()["id"]

    invite_resp = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.MEMBER.value},
    )
    token = invite_resp.json()["token"]

    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Bob as member should not create invite
    response = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "charlie@example.com", "role": Role.MEMBER.value},
    )
    assert response.status_code == 403


def test_accept_invite_becomes_member(client):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Accept", "slug": "accept"})
    ws_id = ws.json()["id"]

    invite_resp = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.MEMBER.value},
    )
    token = invite_resp.json()["token"]

    as_user(client, "bob")
    response = client.post("/invites/accept", json={"token": token})
    assert response.status_code == 201
    assert response.json()["workspace_id"] == ws_id
    assert response.json()["role"] == Role.MEMBER.value

    # Bob can now see the workspace
    response = client.get(f"/workspaces/{ws_id}")
    assert response.status_code == 200


def test_accept_invite_already_accepted_fails(client):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Double", "slug": "double"})
    ws_id = ws.json()["id"]

    invite_resp = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com"},
    )
    token = invite_resp.json()["token"]

    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})
    response = client.post("/invites/accept", json={"token": token})
    assert response.status_code == 409


def test_accept_invite_expired_fails(client, db_session):
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Expired", "slug": "expired"})
    ws_id = ws.json()["id"]

    invite_resp = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com"},
    )
    invite_id = invite_resp.json()["id"]

    # Manually expire invite in the same DB session used by the test client
    invite = db_session.query(WorkspaceInvite).filter(WorkspaceInvite.id == invite_id).first()
    invite.expires_at = _utcnow() - datetime.timedelta(days=1)
    db_session.commit()

    as_user(client, "bob")
    response = client.post("/invites/accept", json={"token": invite.token})
    assert response.status_code == 410


def test_accept_invite_invalid_token_fails(client):
    as_user(client, "bob")
    response = client.post("/invites/accept", json={"token": "not-a-token"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Legacy health/role tests kept for compatibility
# ---------------------------------------------------------------------------

def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_require_role_factory_rejects_unknown_role():
    with pytest.raises(ValueError):
        Role("superuser")


# ---------------------------------------------------------------------------
# Member Management tests
# ---------------------------------------------------------------------------

def test_list_workspace_members_requires_admin(client):
    """Admin can list members, member cannot."""
    # Alice creates workspace
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Org", "slug": "org-members"})
    ws_id = ws.json()["id"]

    # Invite Bob as member
    invite = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.MEMBER.value},
    )
    token = invite.json()["token"]
    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Alice (owner) can list members
    as_user(client, "alice")
    resp = client.get(f"/workspaces/{ws_id}/members")
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 2
    roles = {m["user_id"]: m["role"] for m in members}
    assert roles["alice"] == Role.OWNER.value
    assert roles["bob"] == Role.MEMBER.value

    # Bob (member) cannot list members
    as_user(client, "bob")
    resp = client.get(f"/workspaces/{ws_id}/members")
    assert resp.status_code == 403


def test_update_member_role_admin_can_promote(client):
    """Admin can promote member to admin."""
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Promote", "slug": "promote-test"})
    ws_id = ws.json()["id"]

    # Invite Bob as member
    invite = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.MEMBER.value},
    )
    token = invite.json()["token"]
    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Alice promotes Bob to admin
    as_user(client, "alice")
    resp = client.patch(
        f"/workspaces/{ws_id}/members/bob",
        json={"role": Role.ADMIN.value},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == Role.ADMIN.value


def test_update_member_role_member_cannot_promote(client):
    """Member cannot promote others."""
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "NoPromote", "slug": "nopromote"})
    ws_id = ws.json()["id"]

    # Invite Bob as admin, Charlie as member
    invite_admin = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.ADMIN.value},
    )
    token_admin = invite_admin.json()["token"]
    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token_admin})

    invite_member = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "charlie@example.com", "role": Role.MEMBER.value},
    )
    token_member = invite_member.json()["token"]
    as_user(client, "charlie")
    client.post("/invites/accept", json={"token": token_member})

    # Charlie (member) cannot promote Bob
    as_user(client, "charlie")
    resp = client.patch(
        f"/workspaces/{ws_id}/members/bob",
        json={"role": Role.ADMIN.value},
    )
    assert resp.status_code == 403


def test_update_member_role_cannot_change_owner(client):
    """Cannot change owner's role."""
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "OwnerRole", "slug": "owner-role"})
    ws_id = ws.json()["id"]

    invite = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.ADMIN.value},
    )
    token = invite.json()["token"]
    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Bob (admin) tries to change Alice's (owner) role
    as_user(client, "bob")
    resp = client.patch(
        f"/workspaces/{ws_id}/members/alice",
        json={"role": Role.MEMBER.value},
    )
    assert resp.status_code == 403


def test_remove_member_admin_can_remove(client):
    """Admin can remove member."""
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "RemoveMem", "slug": "remove-mem"})
    ws_id = ws.json()["id"]

    invite = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.MEMBER.value},
    )
    token = invite.json()["token"]
    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Alice removes Bob
    as_user(client, "alice")
    resp = client.delete(f"/workspaces/{ws_id}/members/bob")
    assert resp.status_code == 204

    # Bob no longer in members
    resp = client.get(f"/workspaces/{ws_id}/members")
    members = resp.json()
    assert len(members) == 1
    assert members[0]["user_id"] == "alice"


def test_remove_member_cannot_remove_owner(client):
    """Cannot remove workspace owner."""
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "NoRemoveOwner", "slug": "noremoveowner"})
    ws_id = ws.json()["id"]

    invite = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.ADMIN.value},
    )
    token = invite.json()["token"]
    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Bob (admin) tries to remove Alice (owner)
    as_user(client, "bob")
    resp = client.delete(f"/workspaces/{ws_id}/members/alice")
    assert resp.status_code == 403


def test_transfer_ownership_owner_can_transfer(client):
    """Owner can transfer ownership to another member."""
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "Transfer", "slug": "transfer-test"})
    ws_id = ws.json()["id"]

    invite = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.MEMBER.value},
    )
    token = invite.json()["token"]
    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Alice transfers ownership to Bob
    as_user(client, "alice")
    resp = client.post(
        f"/workspaces/{ws_id}/transfer-ownership",
        json={"user_id": "bob"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_owner_id"] == "bob"

    # Verify roles swapped
    resp = client.get(f"/workspaces/{ws_id}/members")
    members = resp.json()
    roles = {m["user_id"]: m["role"] for m in members}
    assert roles["alice"] == Role.ADMIN.value
    assert roles["bob"] == Role.OWNER.value


def test_transfer_ownership_admin_cannot_transfer(client):
    """Admin cannot transfer ownership."""
    as_user(client, "alice")
    ws = client.post("/workspaces", json={"name": "NoTransfer", "slug": "notransfer"})
    ws_id = ws.json()["id"]

    invite = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": Role.ADMIN.value},
    )
    token = invite.json()["token"]
    as_user(client, "bob")
    client.post("/invites/accept", json={"token": token})

    # Bob (admin) tries to transfer ownership
    as_user(client, "bob")
    resp = client.post(
        f"/workspaces/{ws_id}/transfer-ownership",
        json={"user_id": "alice"},
    )
    assert resp.status_code == 403
