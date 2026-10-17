"""Workspace invitation lifecycle tests using the FastAPI test client.

Previously these tests hit a live server at import time. They now use
TestClient with isolated test databases and real JWT authentication
(shared fixtures from conftest.py).
"""

import uuid

import pytest
from fastapi import HTTPException

from conftest import as_user, make_user


def test_invite_lifecycle(client):
    owner_id = f"invite-owner-{uuid.uuid4().hex[:8]}"
    as_user(client, owner_id)

    slug = f"test-ws-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/workspaces",
        json={"name": "Test WS", "slug": slug, "description": "x"},
    )
    assert r.status_code == 201
    ws_id = r.json()["id"]

    r = client.get(f"/workspaces/{ws_id}/members")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "invitee@example.com", "role": "member"},
    )
    assert r.status_code == 201
    invite = r.json()
    invite_id = invite["id"]
    assert invite["role"] == "member"

    r = client.get(f"/workspaces/{ws_id}/invites")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.patch(
        f"/workspaces/{ws_id}/invites/{invite_id}",
        json={"role": "admin"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "admin"

    r = client.delete(f"/workspaces/{ws_id}/invites/{invite_id}")
    assert r.status_code == 204

    r = client.get(f"/workspaces/{ws_id}/invites")
    assert r.status_code == 200
    assert r.json() == []


def test_duplicate_membership_prevention(client):
    owner_id = f"dup-owner-{uuid.uuid4().hex[:8]}"
    as_user(client, owner_id)
    slug = f"test-ws-{uuid.uuid4().hex[:8]}"
    r = client.post("/workspaces", json={"name": "Test WS", "slug": slug})
    assert r.status_code == 201
    ws_id = r.json()["id"]

    user1_id = f"user1-{uuid.uuid4().hex[:8]}"
    # The invite names the account that redeems it: the client materializes
    # `user1_id` with `<user1_id>@example.com`, so that is the address to offer.
    email = f"{user1_id}@example.com"
    r = client.post(f"/workspaces/{ws_id}/invites", json={"email": email, "role": "member"})
    assert r.status_code == 201
    token1 = r.json()["token"]

    # Accept as user1
    as_user(client, user1_id)
    r = client.post("/invites/accept", json={"token": token1})
    assert r.status_code == 201

    # Second invite as owner
    as_user(client, owner_id)
    r = client.post(f"/workspaces/{ws_id}/invites", json={"email": email, "role": "member"})
    assert r.status_code == 201
    token2 = r.json()["token"]

    # Accept again as user1
    as_user(client, user1_id)
    r = client.post("/invites/accept", json={"token": token2})
    assert r.status_code == 409
    assert r.json()["detail"] == "User is already a member of this workspace"

    # The duplicate invite was consumed anyway (marked accepted) so it does not
    # linger as pending, and no second membership row was created.
    as_user(client, owner_id)
    r = client.get(f"/workspaces/{ws_id}/invites")
    assert r.status_code == 200
    assert r.json() == []

    r = client.get(f"/workspaces/{ws_id}/members")
    assert r.status_code == 200
    members = r.json()
    # owner + user1 exactly once each — no duplicate row for user1
    assert [m["user_id"] for m in members].count(user1_id) == 1
    assert [m["user_id"] for m in members].count(owner_id) == 1


# ---------------------------------------------------------------------------
# SEC-02 — the role an invitation carries is capped
# ---------------------------------------------------------------------------


def _workspace_with_admin(client, db_session):
    """A workspace owned by a fresh user plus one real ADMIN member."""
    owner_id = f"ceil-owner-{uuid.uuid4().hex[:8]}"
    admin_id = f"ceil-admin-{uuid.uuid4().hex[:8]}"
    make_user(db_session, owner_id)
    make_user(db_session, admin_id)

    as_user(client, owner_id)
    created = client.post(
        "/workspaces",
        json={"name": "Ceiling", "slug": f"ceil-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    ws_id = created.json()["id"]

    invite = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": f"{admin_id}@example.com", "role": "admin"},
    )
    assert invite.status_code == 201, invite.text
    as_user(client, admin_id)
    accepted = client.post("/invites/accept", json={"token": invite.json()["token"]})
    assert accepted.status_code == 201, accepted.text
    return ws_id, admin_id


def test_admin_cannot_invite_with_owner_role(client, db_session):
    """An `owner` invite is refused before a row exists — the caller cannot mint an owner."""
    ws_id, admin_id = _workspace_with_admin(client, db_session)

    as_user(client, admin_id)
    resp = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "wanna-be-owner@example.com", "role": "owner"},
    )
    assert resp.status_code == 422, resp.text

    pending = client.get(f"/workspaces/{ws_id}/invites")
    assert pending.status_code == 200
    assert pending.json() == [], "an owner invite was created despite the 422"


def test_invite_role_patch_rejects_owner(client, db_session):
    """Patching a pending invite up to `owner` is refused and leaves the row as it was."""
    ws_id, admin_id = _workspace_with_admin(client, db_session)

    as_user(client, admin_id)
    created = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "patch-me@example.com", "role": "member"},
    )
    assert created.status_code == 201, created.text
    invite_id = created.json()["id"]

    resp = client.patch(f"/workspaces/{ws_id}/invites/{invite_id}", json={"role": "owner"})
    assert resp.status_code == 422, resp.text

    pending = {i["id"]: i for i in client.get(f"/workspaces/{ws_id}/invites").json()}
    assert pending[invite_id]["role"] == "member"


def test_create_invite_handler_refuses_an_owner_that_bypasses_the_schema(
    client, db_session
):
    """The ceiling lives in the router too, so an internal caller cannot skip it."""
    import asyncio
    from types import SimpleNamespace

    from routers.invites import create_invite

    ws_id, admin_id = _workspace_with_admin(client, db_session)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            create_invite(
                workspace_id=ws_id,
                payload=SimpleNamespace(email="direct-call@example.com", role="owner"),
                current_user={"id": admin_id},
                db=db_session,
            )
        )
    assert exc.value.status_code == 403
    assert "owner" in exc.value.detail


def test_admin_can_still_invite_assignable_roles(client, db_session):
    """Positive control: the cap stops `owner`, it does not disable inviting."""
    ws_id, admin_id = _workspace_with_admin(client, db_session)

    as_user(client, admin_id)
    for role in ("member", "guest"):
        resp = client.post(
            f"/workspaces/{ws_id}/invites",
            json={"email": f"ok-{role}@example.com", "role": role},
        )
        assert resp.status_code == 201, f"{role}: {resp.text}"
        assert resp.json()["role"] == role
