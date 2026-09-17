"""TA6-2: query-count guard for the wiki tree endpoint (GET /pages).

The tree view serializes ``PageTreeItem.children`` for every root page.
Before TA6-2 that relationship was lazily loaded during response
serialization, issuing one SELECT per root (N+1): the bench harness measured
304 statements for 300 pages (see docs/PERF-BASELINE.md).

This test seeds a small and a large page set and asserts the statement count
does NOT grow with the number of pages — the same technique as
``test_nplus1_regression.py`` (TA5-1). Pre-fix it fails by ~(large - small).

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


_WS_SEQ = {"n": 0}


def _make_workspace(client: TestClient, db) -> str:
    make_user(db, "owner")
    as_user(client, "owner")
    _WS_SEQ["n"] += 1
    slug = f"kbws{_WS_SEQ['n']}"
    ws = client.post("/workspaces", json={"name": f"KB {slug}", "slug": slug})
    assert ws.status_code == 201, ws.text
    return ws.json()["id"]


def _seed_pages(client: TestClient, workspace_id: str, n: int) -> None:
    """Create n pages: 10 roots, the rest children of the first root."""
    roots = max(1, min(10, n // 3))
    root_ids: list[str] = []
    for i in range(roots):
        resp = client.post(
            f"/workspaces/{workspace_id}/pages",
            json={"title": f"Root {i}", "slug": f"root-{i}-{workspace_id[:8]}-{i}"},
        )
        assert resp.status_code == 201, resp.text
        root_ids.append(resp.json()["id"])
    for i in range(roots, n):
        parent = root_ids[i % len(root_ids)]
        resp = client.post(
            f"/workspaces/{workspace_id}/pages",
            json={
                "title": f"Child {i}",
                "slug": f"child-{i}-{workspace_id[:8]}-{i}",
                "parent_id": parent,
            },
        )
        assert resp.status_code == 201, resp.text


def test_pages_tree_query_count_is_constant_in_number_of_pages(client, db_session):
    ws_small = _make_workspace(client, db_session)
    _seed_pages(client, ws_small, 10)
    with QueryCount() as small:
        resp = client.get(f"/workspaces/{ws_small}/pages")
        assert resp.status_code == 200, resp.text
    assert len(resp.json()) >= 1

    ws_large = _make_workspace(client, db_session)
    _seed_pages(client, ws_large, 100)
    with QueryCount() as large:
        resp = client.get(f"/workspaces/{ws_large}/pages")
        assert resp.status_code == 200, resp.text
    # The tree response must still contain every page somewhere in the tree.
    flat = _flatten(resp.json())
    assert len(flat) == 100, f"tree lost pages: {len(flat)}/100"

    # Statement count must not grow with the number of pages.
    assert large.count <= small.count + 1, (
        f"tree query count grew with rows: small={small.count} large={large.count}"
    )


def test_pages_flat_query_count_is_constant_in_number_of_pages(client, db_session):
    ws_small = _make_workspace(client, db_session)
    _seed_pages(client, ws_small, 10)
    with QueryCount() as small:
        resp = client.get(f"/workspaces/{ws_small}/pages?flat=true")
        assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 10

    ws_large = _make_workspace(client, db_session)
    _seed_pages(client, ws_large, 100)
    with QueryCount() as large:
        resp = client.get(f"/workspaces/{ws_large}/pages?flat=true")
        assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 100

    assert large.count <= small.count + 1, (
        f"flat query count grew with rows: small={small.count} large={large.count}"
    )


def _flatten(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    stack = list(nodes)
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(node.get("children") or [])
    return out
