"""`POST /invites/accept` is bound to the account the invitation names.

The invite token is a bearer string: it is mailed, forwarded, pasted into chat,
kept in browser history, and readable by every admin through the invite list.
A token alone says the invitation changed hands, not that it changed hands *to
the caller* — so every test here answers the same two questions: who is allowed
to redeem it, and what is left of the invitation when they are not.
"""

import asyncio
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException

import models
import schemas
from conftest import as_user, make_user
from dependencies import _utcnow
from routers.invites import accept_invite

_ONE_DAY = timedelta(days=1)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _workspace(client, db_session, owner_id: str) -> str:
    """A workspace owned by ``owner_id``; the client stays authenticated as it."""
    make_user(db_session, owner_id, email=f"{owner_id}@example.com")
    as_user(client, owner_id)
    created = client.post(
        "/workspaces",
        json={"name": "Binding", "slug": f"binding-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _invite(client, workspace_id: str, email: str, role: str = "member") -> dict:
    """Invite ``email``; the client must still be the workspace owner."""
    resp = client.post(f"/workspaces/{workspace_id}/invites", json={"email": email, "role": role})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _roles(db_session, workspace_id: str) -> dict[str, str]:
    """user_id -> role for every membership row in this workspace."""
    db_session.expire_all()
    rows = (
        db_session.query(models.WorkspaceMembership)
        .filter(models.WorkspaceMembership.workspace_id == workspace_id)
        .all()
    )
    return {row.user_id: row.role for row in rows}


def _invite_row(db_session, invite_id: str) -> models.WorkspaceInvite:
    db_session.expire_all()
    return db_session.get(models.WorkspaceInvite, invite_id)


def _expire(db_session, invite_id: str) -> None:
    row = _invite_row(db_session, invite_id)
    row.expires_at = _utcnow() - _ONE_DAY
    db_session.commit()


# ---------------------------------------------------------------------------
# The control: the named invitee still gets the seat
# ---------------------------------------------------------------------------


def test_named_invitee_accepts_and_receives_the_invited_role(client, db_session):
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    invitee_id = _uid("bind-invitee")
    created = _invite(client, workspace_id, email=f"{invitee_id}@example.com", role="admin")

    as_user(client, invitee_id)
    accepted = client.post("/invites/accept", json={"token": created["token"]})

    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["user_id"] == invitee_id
    assert _roles(db_session, workspace_id)[invitee_id] == "admin"


# ---------------------------------------------------------------------------
# The defect: a different authenticated account
# ---------------------------------------------------------------------------


def test_other_account_is_refused_and_the_invite_stays_pending(client, db_session):
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    invitee_id = _uid("bind-invitee")
    stranger_id = _uid("bind-stranger")
    created = _invite(client, workspace_id, email=f"{invitee_id}@example.com")

    as_user(client, stranger_id)
    refused = client.post("/invites/accept", json={"token": created["token"]})

    assert refused.status_code == 403, refused.text
    assert stranger_id not in _roles(db_session, workspace_id)
    # A refused accept must not spend the invitation: `accepted_at` is written
    # only on the paths that create (or consume) a seat.
    assert _invite_row(db_session, created["id"]).accepted_at is None
    # The invitee's address is not the caller's data to read back.
    assert invitee_id not in refused.text

    as_user(client, invitee_id)
    accepted = client.post("/invites/accept", json={"token": created["token"]})
    assert accepted.status_code == 201, accepted.text
    assert _roles(db_session, workspace_id)[invitee_id] == "member"


def test_other_account_cannot_take_an_admin_invite(client, db_session):
    """Same hole at its worst: the refusal grants no role to anybody."""
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    stranger_id = _uid("bind-stranger")
    created = _invite(client, workspace_id, email="someone-else@example.com", role="admin")

    as_user(client, stranger_id)
    refused = client.post("/invites/accept", json={"token": created["token"]})

    assert refused.status_code == 403, refused.text
    assert _roles(db_session, workspace_id) == {owner_id: "owner"}


# ---------------------------------------------------------------------------
# The matching rule ignores case and surrounding whitespace
# ---------------------------------------------------------------------------


def test_address_case_difference_still_redeems(client, db_session):
    """Invited as `UPPER@<host>.Example.COM`, redeemed by the lowercase account.

    `EmailStr` folds the domain and leaves the local part as typed, so these two
    rows really do differ in the table.
    """
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    invitee_id = _uid("bind-invitee")
    created = _invite(client, workspace_id, email=f"UPPER@{invitee_id}.Example.COM")
    make_user(db_session, invitee_id, email=f"upper@{invitee_id}.example.com")

    as_user(client, invitee_id)
    accepted = client.post("/invites/accept", json={"token": created["token"]})

    assert accepted.status_code == 201, accepted.text
    assert _roles(db_session, workspace_id)[invitee_id] == "member"


def test_padded_invited_address_still_redeems(client, db_session):
    """A stored address carrying surrounding blanks stays redeemable.

    Written straight to the table: the create endpoint trims on the way in, so a
    padded row can only come from data that predates that payload path.
    """
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    invitee_id = _uid("bind-invitee")
    invite = models.WorkspaceInvite(
        workspace_id=workspace_id,
        email=f"  {invitee_id}@example.com  ",
        role="member",
        expires_at=_utcnow() + _ONE_DAY,
    )
    db_session.add(invite)
    db_session.commit()

    as_user(client, invitee_id)
    accepted = client.post("/invites/accept", json={"token": invite.token})

    assert accepted.status_code == 201, accepted.text
    assert _roles(db_session, workspace_id)[invitee_id] == "member"


# ---------------------------------------------------------------------------
# Check order: 404, then 403, then 409, then 410
# ---------------------------------------------------------------------------


def test_unknown_token_is_404_not_403(client, db_session):
    owner_id = _uid("bind-owner")
    _workspace(client, db_session, owner_id)

    as_user(client, owner_id)
    resp = client.post("/invites/accept", json={"token": "no-such-token"})

    assert resp.status_code == 404, resp.text


def test_wrong_person_on_a_redeemed_invite_is_403_not_409(client, db_session):
    """The identity failure outranks the conflict, so an invite somebody already
    spent cannot mask the fact that a second, wrong account tried to use it."""
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    invitee_id = _uid("bind-invitee")
    stranger_id = _uid("bind-stranger")
    created = _invite(client, workspace_id, email=f"{invitee_id}@example.com")

    as_user(client, invitee_id)
    assert client.post("/invites/accept", json={"token": created["token"]}).status_code == 201

    as_user(client, stranger_id)
    resp = client.post("/invites/accept", json={"token": created["token"]})

    assert resp.status_code == 403, resp.text
    assert stranger_id not in _roles(db_session, workspace_id)


def test_second_accept_by_the_named_invitee_is_409(client, db_session):
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    invitee_id = _uid("bind-invitee")
    created = _invite(client, workspace_id, email=f"{invitee_id}@example.com")

    as_user(client, invitee_id)
    first = client.post("/invites/accept", json={"token": created["token"]})
    assert first.status_code == 201, first.text

    second = client.post("/invites/accept", json={"token": created["token"]})
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "Invite already accepted"


def test_expired_invite_is_410_for_the_named_invitee(client, db_session):
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    invitee_id = _uid("bind-invitee")
    created = _invite(client, workspace_id, email=f"{invitee_id}@example.com")
    _expire(db_session, created["id"])

    as_user(client, invitee_id)
    resp = client.post("/invites/accept", json={"token": created["token"]})

    assert resp.status_code == 410, resp.text
    assert invitee_id not in _roles(db_session, workspace_id)


def test_wrong_person_on_an_expired_invite_is_403_not_410(client, db_session):
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    stranger_id = _uid("bind-stranger")
    created = _invite(client, workspace_id, email="someone-else@example.com")
    _expire(db_session, created["id"])

    as_user(client, stranger_id)
    resp = client.post("/invites/accept", json={"token": created["token"]})

    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# The pre-existing duplicate-membership path, for the right person only
# ---------------------------------------------------------------------------


def test_named_invitee_who_is_already_a_member_still_consumes_the_invite(
    client, db_session
):
    """409 with the "already a member" detail, that invite spent, no second row."""
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    invitee_id = _uid("bind-invitee")
    first = _invite(client, workspace_id, email=f"{invitee_id}@example.com")

    as_user(client, invitee_id)
    assert client.post("/invites/accept", json={"token": first["token"]}).status_code == 201

    as_user(client, owner_id)
    second = _invite(client, workspace_id, email=f"{invitee_id}@example.com")

    as_user(client, invitee_id)
    resp = client.post("/invites/accept", json={"token": second["token"]})

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "User is already a member of this workspace"
    assert _invite_row(db_session, second["id"]).accepted_at is not None
    # Count the ROWS, not the keys of `_roles`: that helper is keyed by user_id, so
    # a second membership row for this user would overwrite its own key and the
    # key list would still name them exactly once — an assertion that cannot fail.
    assert (
        db_session.query(models.WorkspaceMembership)
        .filter(
            models.WorkspaceMembership.workspace_id == workspace_id,
            models.WorkspaceMembership.user_id == invitee_id,
        )
        .count()
        == 1
    ), "a duplicate membership row exists for the named invitee"


# ---------------------------------------------------------------------------
# Fail-closed: an identity the accounts table does not know has no address, and
# that is not a wildcard. Reached by calling the handler directly, because the
# test client materializes a User row for every JWT subject it is given.
# ---------------------------------------------------------------------------


def test_identity_without_an_account_row_is_refused(client, db_session):
    owner_id = _uid("bind-owner")
    workspace_id = _workspace(client, db_session, owner_id)
    created = _invite(client, workspace_id, email="someone-else@example.com")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            accept_invite(
                payload=schemas.InviteAccept(token=created["token"]),
                current_user={"id": _uid("bind-ghost")},
                db=db_session,
            )
        )

    assert exc.value.status_code == 403
    assert _invite_row(db_session, created["id"]).accepted_at is None
    assert _roles(db_session, workspace_id) == {owner_id: "owner"}
