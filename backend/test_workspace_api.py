"""Workspace API tests using the FastAPI test client.

Previously these tests hit a live server at import time, which caused
non-deterministic failures when the server was down or when test data
conflicted. They now use TestClient and real JWT authentication (shared
fixtures from conftest.py) so the full suite is isolated and hermetic.
"""

import datetime
import uuid

import models
from conftest import as_user, make_user


def test_workspace_members_flow(client):
    owner_id = f"ws-owner-{uuid.uuid4().hex[:8]}"
    as_user(client, owner_id)

    slug = f"test-ws-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/workspaces",
        json={"name": "Test WS", "slug": slug, "description": "x"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test WS"
    ws_id = data["id"]

    r = client.get(f"/workspaces/{ws_id}/members")
    assert r.status_code == 200
    members = r.json()
    assert len(members) == 1
    assert members[0]["user_id"] == owner_id

    r = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "invitee@example.com", "role": "member"},
    )
    assert r.status_code == 201
    invite = r.json()
    assert invite["email"] == "invitee@example.com"
    assert invite["role"] == "member"

    r = client.get(f"/workspaces/{ws_id}/invites")
    assert r.status_code == 200
    invites = r.json()
    assert len(invites) == 1
    assert invites[0]["email"] == "invitee@example.com"


def test_list_workspaces_orders_by_created_at(client, db_session):
    """`GET /workspaces` comes back oldest-first, which is what the BFF's `[0]` means.

    The order is load-bearing, not cosmetic: every BFF handler resolves "the
    current workspace" as the first entry of this list (docs/API.md, "Frontend
    BFF mapping"), and it re-resolves per request — `api/presence`, `api/pages`,
    `api/files` and the rest each do their own `GET /workspaces`. Without a sort
    the header bell and the sidebar can then be looking at two different
    workspaces in one page load.

    Written so it cannot pass by accident. `created_at` is set to the exact
    reverse of the `id` order, and the rows are inserted in a third order again.
    That matters because the unordered query is not random on SQLite:
    `WHERE id IN (...)` is a SEARCH on `sqlite_autoindex_workspaces_1`, so it
    already returns id-ascending. Asserting the created_at order against that
    means a build with no `order_by` answers in id order and fails here, instead
    of passing on the incident that made the missing sort invisible.
    """
    owner = f"ws-order-{uuid.uuid4().hex[:8]}"
    as_user(client, owner)
    created = []
    for slug in ("ws-a", "ws-b", "ws-c"):
        r = client.post("/workspaces", json={"name": slug, "slug": slug})
        assert r.status_code == 201
        created.append((r.json()["id"], slug))
    by_id = sorted(created)

    # Naive UTC, the stored convention on both engines (docs/API.md "IDs";
    # `test_dialect_parity.py` pins it): smallest id is the newest workspace.
    base = datetime.datetime(2026, 1, 1, 0, 0, 0)
    for rank, (ws_id, _slug) in enumerate(by_id):
        row = db_session.query(models.Workspace).filter(models.Workspace.id == ws_id).one()
        row.created_at = base + datetime.timedelta(days=len(by_id) - 1 - rank)
    db_session.commit()

    expected = [ws_id for ws_id, _slug in reversed(by_id)]
    data = client.get("/workspaces").json()
    assert [w["id"] for w in data] == expected
    # The stability the BFF actually needs: two requests, same answer. One call
    # is not enough to show the bug this sort exists for.
    assert client.get("/workspaces").json() == data


def test_list_workspaces_breaks_created_at_ties_by_id(client, db_session):
    """Two workspaces with the same `created_at` are ordered by `id`.

    `created_at` is not unique, and the tie is not exotic: SQLite's
    `(CURRENT_TIMESTAMP)` default has second resolution, and on PostgreSQL
    `func.now()` is the *transaction* timestamp — so every workspace created in
    one transaction ties, and the primary key decides nothing. `id` is the
    primary key, so the tiebreak cannot itself tie: that is what makes the order
    total rather than merely usually-right.

    Honest about its own coverage: this assertion cannot fail on SQLite, because
    the unordered plan there is the primary-key index scan, which is already
    id-ascending — the same answer the sort gives. `backend-pg` is the job that
    would catch a dropped tiebreak (a sequential scan returns physical order,
    which is `charlie, bravo, alpha` here). It is committed anyway because the
    contract is the thing the BFF relies on, and a test that documents a
    contract one engine satisfies by coincidence is worth keeping out loud —
    see `test_list_workspaces_orders_by_created_at`, which is the half that does
    fail on SQLite.
    """
    owner = f"ws-tie-{uuid.uuid4().hex[:8]}"
    make_user(db_session, owner)
    same_instant = datetime.datetime(2026, 1, 1, 12, 0, 0)
    for ws_id in ("ws-tie-charlie", "ws-tie-bravo", "ws-tie-alpha"):
        db_session.add(
            models.Workspace(
                id=ws_id,
                name=ws_id,
                slug=ws_id,
                created_at=same_instant,
                updated_at=same_instant,
            )
        )
        db_session.add(
            models.WorkspaceMembership(
                workspace_id=ws_id, user_id=owner, role="owner", joined_at=same_instant
            )
        )
    db_session.commit()

    as_user(client, owner)
    data = client.get("/workspaces").json()
    assert [w["id"] for w in data] == ["ws-tie-alpha", "ws-tie-bravo", "ws-tie-charlie"]
