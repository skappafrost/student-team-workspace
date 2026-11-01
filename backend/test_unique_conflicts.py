"""COR-18 — losing a read-then-insert race must answer 409, not 500.

Every create path looks for the duplicate first and then inserts. The lookup and
the INSERT are separate statements, so a second in-flight request — a
double-click, two tabs, a client retry — can put the same UNIQUE value in the
table in between. The constraint then fires inside the request as an unhandled
``IntegrityError``: HTTP 500, and the session left inside a failed transaction.

``race_a_write`` opens that window on purpose. A thread race would be the more
literal reproduction, but on SQLite the loser is as likely to get a lock timeout
as the violation under test, so the interleaving is injected rather than raced:
the competing row is queued at the flush that writes the route's own row, which
is after its duplicate check and before its INSERT.

What stays real is the part being judged: the live route, the model's own UNIQUE
constraint, and the persisted rows afterwards. Each test also asserts the
injection fired, so it cannot pass by hitting the duplicate *pre-check* instead
of the race handler — the two answer the same 409 with the same text.
"""

import pytest
from sqlalchemy import event

import models
from conftest import as_user, make_user


def race_a_write(db_session, table, make_row):
    """Queue ``make_row()`` into the request's own flush for ``table``, once.

    Returns a list that records the firing; one element means the collision was
    real, an empty list means the request answered before reaching the write.
    """
    fired = []

    def _listener(session, flush_context, instances):
        if fired:
            return
        pending = {type(obj).__tablename__ for obj in list(session.new) + list(session.dirty)}
        if table not in pending:
            return
        fired.append(table)
        session.add(make_row())

    event.listen(db_session, "before_flush", _listener)
    return fired


def _count(db_session, model, **filters):
    query = db_session.query(model)
    for column, value in filters.items():
        query = query.filter(getattr(model, column) == value)
    return query.count()


@pytest.fixture()
def workspace(client, db_session):
    """A real owner plus the workspace they just created over HTTP."""
    make_user(db_session, "owner")
    as_user(client, "owner")
    resp = client.post("/workspaces", json={"name": "WS", "slug": "race-ws", "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def channel(client, workspace):
    """A public channel in :data:`workspace`."""
    resp = client.post(
        f"/workspaces/{workspace['id']}/channels", json={"name": "gen", "type": "general"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# users.email
# ---------------------------------------------------------------------------


def test_register_loses_the_email_race_to_409(client, db_session):
    fired = race_a_write(
        db_session,
        "users",
        lambda: models.User(id="race-winner", email="race@example.com", display_name="Winner"),
    )
    resp = client.post(
        "/auth/register", json={"email": "race@example.com", "password": "Sup3rSecret!"}
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Email already registered"
    assert fired == ["users"], "the pre-check answered, not the race handler"
    # The loser persists nothing — and the rollback leaves the session usable,
    # which is what the follow-up request below proves.
    assert _count(db_session, models.User, email="race@example.com") == 0
    assert _count(db_session, models.User, email="second@example.com") == 0
    again = client.post(
        "/auth/register", json={"email": "second@example.com", "password": "Sup3rSecret!"}
    )
    assert again.status_code == 201, again.text
    assert _count(db_session, models.User, email="second@example.com") == 1


# ---------------------------------------------------------------------------
# workspaces.slug (create and rename)
# ---------------------------------------------------------------------------


def test_creating_a_workspace_loses_the_slug_race_to_409(client, db_session, workspace):
    fired = race_a_write(
        db_session,
        "workspaces",
        lambda: models.Workspace(id="race-ws", name="R", slug="taken"),
    )
    resp = client.post("/workspaces", json={"name": "Mine", "slug": "taken", "description": "x"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Workspace slug already exists"
    assert fired == ["workspaces"], "the pre-check answered, not the race handler"
    assert _count(db_session, models.Workspace, slug="taken") == 0
    again = client.post("/workspaces", json={"name": "Mine", "slug": "mine", "description": "x"})
    assert again.status_code == 201, again.text


def test_renaming_a_workspace_loses_the_slug_race_to_409(client, db_session, workspace):
    fired = race_a_write(
        db_session,
        "workspaces",
        lambda: models.Workspace(id="race-ws2", name="R", slug="taken"),
    )
    resp = client.patch(f"/workspaces/{workspace['id']}", json={"slug": "taken"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Workspace slug already exists"
    assert fired == ["workspaces"], "the pre-check answered, not the race handler"
    db_session.expire_all()
    kept = db_session.get(models.Workspace, workspace["id"])
    assert kept.slug == "race-ws", "the losing rename persisted its slug"
    again = client.patch(f"/workspaces/{workspace['id']}", json={"name": "Renamed"})
    assert again.status_code == 200, again.text
    assert again.json()["name"] == "Renamed"


# ---------------------------------------------------------------------------
# workspace_members (workspace_id, user_id)
# ---------------------------------------------------------------------------


def test_accepting_an_invite_loses_the_membership_race_to_409(client, db_session, workspace):
    invite = client.post(
        f"/workspaces/{workspace['id']}/invites",
        json={"email": "guest@example.com", "role": "member"},
    )
    assert invite.status_code == 201, invite.text
    token = invite.json()["token"]

    make_user(db_session, "guest", email="guest@example.com")
    as_user(client, "guest")
    fired = race_a_write(
        db_session,
        "workspace_members",
        lambda: models.WorkspaceMembership(
            workspace_id=workspace["id"], user_id="guest", role="member"
        ),
    )
    resp = client.post("/invites/accept", json={"token": token})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "User is already a member of this workspace"
    assert fired == ["workspace_members"], "the pre-check answered, not the race handler"
    assert _count(db_session, models.WorkspaceMembership, user_id="guest") == 0
    # The failed accept rolled back with the membership: the invite is still
    # pending, so the retry that a client would make now succeeds.
    again = client.post("/invites/accept", json={"token": token})
    assert again.status_code == 201, again.text
    assert _count(db_session, models.WorkspaceMembership, user_id="guest") == 1


# ---------------------------------------------------------------------------
# channel_members (channel_id, user_id)
# ---------------------------------------------------------------------------


def test_adding_a_channel_member_loses_the_membership_race_to_409(
    client, db_session, workspace, channel
):
    make_user(db_session, "guest", email="guest@example.com")
    db_session.add(
        models.WorkspaceMembership(
            workspace_id=workspace["id"], user_id="guest", role="member"
        )
    )
    db_session.commit()
    private = client.post(
        f"/workspaces/{workspace['id']}/channels", json={"name": "secret", "type": "private"}
    )
    assert private.status_code == 201, private.text

    fired = race_a_write(
        db_session,
        "channel_members",
        lambda: models.ChannelMember(channel_id=private.json()["id"], user_id="guest"),
    )
    resp = client.post(
        f"/channels/{private.json()['id']}/members", json={"user_id": "guest"}
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "User is already a member of this channel"
    assert fired == ["channel_members"], "the pre-check answered, not the race handler"
    assert _count(db_session, models.ChannelMember, user_id="guest") == 0
    again = client.post(
        f"/channels/{private.json()['id']}/members", json={"user_id": "guest"}
    )
    assert again.status_code == 201, again.text
    assert _count(db_session, models.ChannelMember, user_id="guest") == 1


# ---------------------------------------------------------------------------
# message_reactions (message_id, user_id, emoji)
# ---------------------------------------------------------------------------


def test_toggling_a_reaction_loses_the_insert_race_to_409(client, db_session, channel):
    message = client.post(f"/channels/{channel['id']}/messages", json={"content": "hi"})
    assert message.status_code == 201, message.text
    message_id = message.json()["id"]

    fired = race_a_write(
        db_session,
        "message_reactions",
        lambda: models.MessageReaction(message_id=message_id, user_id="owner", emoji="👍"),
    )
    resp = client.post(f"/messages/{message_id}/reactions", json={"emoji": "👍"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Reaction already recorded"
    assert fired == ["message_reactions"], "the pre-check answered, not the race handler"
    assert _count(db_session, models.MessageReaction, message_id=message_id) == 0
    again = client.post(f"/messages/{message_id}/reactions", json={"emoji": "👍"})
    assert again.status_code == 200, again.text
    assert _count(db_session, models.MessageReaction, message_id=message_id) == 1


# ---------------------------------------------------------------------------
# presence_state (workspace_id, user_id) — an upsert, so the answer is the row
# ---------------------------------------------------------------------------


def test_presence_losing_its_own_insert_still_records_one_row(client, db_session, workspace):
    """A heartbeat cannot answer 409: the client has nothing to do with it.

    The second writer takes the row that won instead of failing, so the member
    ends up with exactly one presence row carrying the requested status.
    """
    fired = race_a_write(
        db_session,
        "presence_state",
        lambda: models.PresenceState(
            workspace_id=workspace["id"], user_id="owner", status="online"
        ),
    )
    resp = client.post(
        f"/workspaces/{workspace['id']}/presence/me",
        json={"status": "dnd", "status_message": "Heads down"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "dnd"
    assert fired == ["presence_state"], "no race happened, so the retry path went untested"
    rows = db_session.query(models.PresenceState).filter_by(user_id="owner").all()
    assert len(rows) == 1, f"{len(rows)} presence rows for one member"
    assert rows[0].status == "dnd"
    assert rows[0].status_message == "Heads down"
