"""Uniform pagination contract (TA3-1).

Covers, for representative collection endpoints:
  * the hard cap is enforced (limit > MAX_LIST_LIMIT -> 422);
  * defaults are applied when the client omits limit/offset;
  * offset works (page windows return disjoint sets in a stable order);
  * existing response shapes are unchanged (top-level JSON array, same fields).

Contract lives in backend/pagination.py; see docs/API.md "Pagination".
"""

import pagination as pagination_lib
from conftest import as_user, make_user

# ---------------------------------------------------------------------------
# Fixtures / seed helpers (self-contained, real JWT only)
# ---------------------------------------------------------------------------

def _create_workspace(client, user_id="owner", name="WS", slug="ws"):
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_notifications(client, db_session, user_id, n):
    make_user(db_session, user_id, email=f"{user_id}@example.com")
    as_user(client, user_id)
    for i in range(n):
        resp = client.post(
            "/notifications",
            json={
                "user_id": user_id,
                "type": "task-assigned",
                "title": f"notif {i:03d}",
                "content": f"body {i}",
            },
        )
        assert resp.status_code == 201, resp.text


def _seed_channels(client, ws_id, n, user_id="owner"):
    as_user(client, user_id)
    for i in range(n):
        resp = client.post(
            f"/workspaces/{ws_id}/channels",
            json={"name": f"chan-{i:03d}", "type": "general"},
        )
        assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Unit: helper contract
# ---------------------------------------------------------------------------

def test_parse_list_params_defaults():
    assert pagination_lib.parse_list_params(None, None) == (
        pagination_lib.DEFAULT_LIST_LIMIT,
        0,
    )
    # the contract default is the cap itself (full-collection semantics)
    assert pagination_lib.DEFAULT_LIST_LIMIT == pagination_lib.MAX_LIST_LIMIT


def test_parse_list_params_clamps_and_none_default():
    assert pagination_lib.parse_list_params(0, -5) == (1, 0)
    # explicit None default = "return the full collection" endpoint policy
    assert pagination_lib.parse_list_params(None, None, default=None) == (None, 0)
    # custom cap (audit-log style)
    assert pagination_lib.parse_list_params(99999, None, default=100, max_limit=500) == (
        500,
        0,
    )


def test_max_list_limit_is_1000():
    assert pagination_lib.MAX_LIST_LIMIT == 1000


# ---------------------------------------------------------------------------
# Notifications: cap enforced, defaults applied, offset works, shape frozen
# ---------------------------------------------------------------------------

def test_notifications_default_returns_full_collection(client, db_session):
    """Omitted limit = the contract's default (== the 1000 cap): full set.

    BFF clients never pass limit and rely on receiving the whole array
    (frozen behaviour), so the default must not truncate realistic sizes.
    """
    _create_workspace(client)
    _seed_notifications(client, db_session, "reader", 60)
    as_user(client, "reader")
    resp = client.get("/notifications")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 60
    # an explicit smaller limit does page
    assert len(client.get("/notifications?limit=25").json()) == 25


def test_notifications_custom_limit_and_offset(client, db_session):
    _create_workspace(client)
    _seed_notifications(client, db_session, "reader", 10)
    as_user(client, "reader")
    first = client.get("/notifications?limit=3&offset=0").json()
    second = client.get("/notifications?limit=3&offset=3").json()
    assert len(first) == 3 and len(second) == 3
    assert {n["id"] for n in first}.isdisjoint({n["id"] for n in second})
    # offset beyond the end -> empty, not error
    assert client.get("/notifications?offset=99").json() == []


def test_notifications_hard_cap_enforced(client, db_session):
    _create_workspace(client)
    _seed_notifications(client, db_session, "reader", 3)
    as_user(client, "reader")
    resp = client.get(f"/notifications?limit={pagination_lib.MAX_LIST_LIMIT + 1}")
    assert resp.status_code == 422
    # negative offset rejected
    assert client.get("/notifications?offset=-1").status_code == 422


def test_notifications_shape_unchanged(client, db_session):
    _create_workspace(client)
    _seed_notifications(client, db_session, "reader", 1)
    as_user(client, "reader")
    data = client.get("/notifications").json()
    assert len(data) == 1
    assert set(data[0]) == {
        "id",
        "user_id",
        "type",
        "title",
        "content",
        "link",
        "read",
        "created_at",
    }


# ---------------------------------------------------------------------------
# Channels: same contract on a second representative endpoint
# ---------------------------------------------------------------------------

def test_channels_default_returns_full_collection(client, db_session):
    ws = _create_workspace(client)
    _seed_channels(client, ws["id"], 60)
    data = client.get(f"/workspaces/{ws['id']}/channels").json()
    assert isinstance(data, list)
    assert len(data) == 60  # default == cap: nothing truncated
    assert len(client.get(f"/workspaces/{ws['id']}/channels?limit=25").json()) == 25


def test_channels_offset_windows_disjoint(client, db_session):
    ws = _create_workspace(client)
    _seed_channels(client, ws["id"], 10)
    a = client.get(f"/workspaces/{ws['id']}/channels?limit=4&offset=0").json()
    b = client.get(f"/workspaces/{ws['id']}/channels?limit=4&offset=4").json()
    assert len(a) == 4 and len(b) == 4
    assert {c["id"] for c in a}.isdisjoint({c["id"] for c in b})
    # deterministic order across pages
    names = [c["name"] for c in a] + [c["name"] for c in b]
    assert names == sorted(names)


def test_channels_hard_cap_enforced(client, db_session):
    ws = _create_workspace(client)
    _seed_channels(client, ws["id"], 3)
    resp = client.get(f"/workspaces/{ws['id']}/channels?limit=99999")
    assert resp.status_code == 422


def test_channels_shape_unchanged(client, db_session):
    ws = _create_workspace(client)
    _seed_channels(client, ws["id"], 1)
    data = client.get(f"/workspaces/{ws['id']}/channels").json()
    assert len(data) == 1
    assert set(data[0]) == {
        "id",
        "workspace_id",
        "name",
        "type",
        "created_by",
        "is_private",
        "created_at",
    }


# ---------------------------------------------------------------------------
# Pre-existing params keep working (regression: no accidental rename)
# ---------------------------------------------------------------------------

def test_audit_log_limit_offset_still_accepted(client, db_session):
    make_user(db_session, "u1", email="u1@example.com")
    as_user(client, "u1")
    ws = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P"}).json()
    for i in range(5):
        client.post(f"/projects/{proj['id']}/tasks", json={"title": f"t{i}"})
    page1 = client.get(f"/workspaces/{ws['id']}/audit-log?limit=1&offset=0").json()
    page2 = client.get(f"/workspaces/{ws['id']}/audit-log?limit=1&offset=1").json()
    assert len(page1) == 1 and len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]


def test_activity_feed_limit_still_bounded(client, db_session):
    make_user(db_session, "u1", email="u1@example.com")
    as_user(client, "u1")
    ws = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()
    proj = client.post(f"/workspaces/{ws['id']}/projects", json={"name": "P"}).json()
    for i in range(10):
        client.post(f"/projects/{proj['id']}/tasks", json={"title": f"t{i}"})
    # default cap is 100, well above the 10 generated entries
    default_rows = client.get(f"/workspaces/{ws['id']}/activity").json()
    assert 5 <= len(default_rows) <= 100
    limited = client.get(f"/workspaces/{ws['id']}/activity?limit=3").json()
    assert len(limited) == 3
    # the pre-existing clamp at 100 still holds
    assert len(client.get(f"/workspaces/{ws['id']}/activity?limit=99999").json()) <= 100
