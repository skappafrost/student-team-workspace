"""TA5-1: query-count regression guards for the list endpoints that used to
issue one SELECT per row (N+1).

Method: a ``before_cursor_execute`` counter wrapped around the measured
request. Each test seeds the same endpoint twice — with a small and a large
row count — and asserts the query count does NOT grow with the rows.
Pre-batching every assertion here fails by ~(large - small) queries.

Real JWT auth only (make_user/as_user from conftest), per repo policy.
"""

import sqlalchemy as sa
from fastapi.testclient import TestClient

from conftest import as_user, make_user
from database import engine


class QueryCount:
    """Context manager counting statements executed on the app engine."""

    def __init__(self) -> None:
        self.count = 0

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1

    def __enter__(self) -> "QueryCount":
        sa.event.listen(engine, "before_cursor_execute", self._before)
        return self

    def __exit__(self, *exc) -> None:
        sa.event.remove(engine, "before_cursor_execute", self._before)


# ---------------------------------------------------------------------------
# Seeding helpers (mirror test_dm_api's invite/accept flow)
# ---------------------------------------------------------------------------


_WS_SEQ = {"n": 0}


def _make_workspace(client: TestClient, db) -> str:
    make_user(db, "owner")
    as_user(client, "owner")
    _WS_SEQ["n"] += 1
    slug = f"ws{_WS_SEQ['n']}"
    ws = client.post("/workspaces", json={"name": f"WS {slug}", "slug": slug})
    assert ws.status_code == 201, ws.text
    return ws.json()["id"]


def _add_member(client: TestClient, db, workspace_id: str, user_id: str) -> None:
    inv = client.post(
        f"/workspaces/{workspace_id}/invites",
        json={"email": f"{user_id}@example.com", "role": "member"},
    )
    assert inv.status_code == 201, inv.text
    make_user(db, user_id)
    as_user(client, user_id)
    accept = client.post("/invites/accept", json={"token": inv.json()["token"]})
    assert accept.status_code == 201, accept.text
    as_user(client, "owner")


def _seed_dms(client: TestClient, db, workspace_id: str, n: str) -> list[str]:
    """Create ``n`` DM channels between owner and peers p0..p{n-1}."""
    ids = []
    for i in range(int(n)):
        peer = f"p{i}"
        _add_member(client, db, workspace_id, peer)
        dm = client.post(
            f"/workspaces/{workspace_id}/dms", json={"user_id": peer}
        )
        assert dm.status_code == 201, dm.text
        ids.append(dm.json()["id"])
    return ids


# ---------------------------------------------------------------------------
# GET /workspaces/{id}/dms — was 1 peer query per DM channel
# ---------------------------------------------------------------------------


def test_list_dms_query_count_is_constant_in_number_of_dms(client, db_session):
    ws_small = _make_workspace(client, db_session)
    _seed_dms(client, db_session, ws_small, 2)
    with QueryCount() as small:
        resp = client.get(f"/workspaces/{ws_small}/dms")
        assert resp.status_code == 200

    # Second workspace with 8 DMs (fresh DB per test not needed: separate ws).
    _seed_dms(client, db_session, ws_small, 0)  # no-op guard for linters
    ws_big = _make_workspace(client, db_session)
    _seed_dms(client, db_session, ws_big, 8)
    with QueryCount() as big:
        resp = client.get(f"/workspaces/{ws_big}/dms")
        assert resp.status_code == 200
        assert len(resp.json()) == 8

    assert big.count - small.count <= 1, (
        f"list_dms query count grew with DM count ({small.count} -> {big.count}): "
        "per-row peer lookups are back"
    )


def test_list_dms_keeps_peer_fields_correct(client, db_session):
    ws = _make_workspace(client, db_session)
    _seed_dms(client, db_session, ws, 3)
    make_user(db_session, "p9", display_name="Peer Nine")
    _add_member(client, db_session, ws, "p9")
    dm = client.post(f"/workspaces/{ws}/dms", json={"user_id": "p9"})
    assert dm.status_code == 201

    resp = client.get(f"/workspaces/{ws}/dms")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 4
    mine = [i for i in items if i["peer_id"] == "p9"]
    assert len(mine) == 1 and mine[0]["peer_name"] == "Peer Nine"
    assert all(i["type"] == "dm" for i in items)


# ---------------------------------------------------------------------------
# POST /workspaces/{id}/dms dedup — was 1 ChannelMember query per candidate DM
# ---------------------------------------------------------------------------


def test_create_dm_dedup_query_count_is_constant(client, db_session):
    ws_small = _make_workspace(client, db_session)
    peers = _seed_dms(client, db_session, ws_small, 2)
    existing = client.post(f"/workspaces/{ws_small}/dms", json={"user_id": "p0"})
    assert existing.status_code == 201
    with QueryCount() as small:
        resp = client.post(f"/workspaces/{ws_small}/dms", json={"user_id": "p0"})
        assert resp.status_code == 201
    assert resp.json()["id"] == existing.json()["id"]
    del peers

    ws_big = _make_workspace(client, db_session)
    _seed_dms(client, db_session, ws_big, 8)
    dup = client.post(f"/workspaces/{ws_big}/dms", json={"user_id": "p0"})
    assert dup.status_code == 201
    with QueryCount() as big:
        resp = client.post(f"/workspaces/{ws_big}/dms", json={"user_id": "p0"})
        assert resp.status_code == 201
    assert resp.json()["id"] == dup.json()["id"]

    assert big.count - small.count <= 1, (
        f"create_dm dedup scans candidates per row ({small.count} -> {big.count}): "
        "member lookup must be one batched query"
    )


# ---------------------------------------------------------------------------
# GET /ai/search — was 1 lazy SELECT per task (project) / message (channel)
# ---------------------------------------------------------------------------


def _seed_projects_with_tasks(client: TestClient, db, workspace_id: str, n: int):
    for i in range(n):
        proj = client.post(
            f"/workspaces/{workspace_id}/projects",
            json={"name": f"Project {i}", "description": ""},
        )
        assert proj.status_code == 201, proj.text
        task = client.post(
            f"/projects/{proj.json()['id']}/tasks",
            json={"title": "alpha task", "description": "searchable"},
        )
        assert task.status_code == 201, task.text


def _seed_channel_with_messages(client: TestClient, db, workspace_id: str, n: int):
    ch = client.post(
        f"/workspaces/{workspace_id}/channels",
        json={"name": f"chan{n}", "type": "general"},
    )
    assert ch.status_code == 201, ch.text
    for i in range(n):
        msg = client.post(
            f"/channels/{ch.json()['id']}/messages",
            json={"content": f"alpha message {i} here"},
        )
        assert msg.status_code == 201, msg.text


def test_ai_search_task_results_scale_constant(client, db_session):
    # NOTE: /ai/search spans every workspace the user belongs to, so the
    # second workspace's rows are additive (2 then 2+8). Query count must
    # stay flat as rows grow.
    ws_small = _make_workspace(client, db_session)
    _seed_projects_with_tasks(client, db_session, ws_small, 2)
    with QueryCount() as small:
        resp = client.get("/ai/search", params={"q": "alpha", "scope": "tasks"})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 2

    ws_big = _make_workspace(client, db_session)
    _seed_projects_with_tasks(client, db_session, ws_big, 8)
    with QueryCount() as big:
        resp = client.get("/ai/search", params={"q": "alpha", "scope": "tasks"})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 10

    assert big.count - small.count <= 1, (
        f"ai/search tasks lazy-load task.project per row "
        f"({small.count} -> {big.count})"
    )


def test_ai_search_message_results_scale_constant(client, db_session):
    # Additive across workspaces (same note as the tasks test above).
    ws_small = _make_workspace(client, db_session)
    _seed_channel_with_messages(client, db_session, ws_small, 2)
    with QueryCount() as small:
        resp = client.get("/ai/search", params={"q": "alpha", "scope": "messages"})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 2

    ws_big = _make_workspace(client, db_session)
    _seed_channel_with_messages(client, db_session, ws_big, 8)
    with QueryCount() as big:
        resp = client.get("/ai/search", params={"q": "alpha", "scope": "messages"})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 10

    assert big.count - small.count <= 1, (
        f"ai/search messages lazy-load message.channel per row "
        f"({small.count} -> {big.count})"
    )
