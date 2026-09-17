"""STW backend read-path benchmark harness (TA6-2).

NOT part of the pytest suite: this module is imported by ``bench/run_bench.py``
explicitly and is never collected by ``pytest`` (the ``bench/`` tree sits
outside pytest's rootdir collection path and contains no ``test_*`` modules).

Design constraints (from TA6-2):
  * no new heavy deps        -> stdlib only, plus the repo's own SQLAlchemy
  * opt-in, never collected  -> run explicitly: ``python bench/run_bench.py``
  * numbers, not vibes       -> p50/p95 wall-clock + SQLAlchemy statement count
                               per hot read endpoint, at several row counts
  * dialect portable         -> runs on the local SQLite dev DB by default and
                               on CI Postgres via DATABASE_URL; the reported
                               numbers are always labelled with the dialect

Measured hot paths (all read-only, all production endpoints):
  1. GET /workspaces/{id}/kanban summary  (board list: channels + tasks)
  2. GET /channels/{id}/messages          (paginated message list)
  3. GET /notifications                   (notifications list)
  4. GET /workspaces/{id}/files           (file list)
  5. GET /workspaces/{id}/pages           (wiki tree)

Latency is measured end-to-end through FastAPI's TestClient (middleware +
serialization included) so the numbers reflect what a real client sees.
Statement counts are captured with a ``before_cursor_execute`` event listener
on the engine, the same approach as ``test_nplus1_regression.py`` (TA5-1).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient

import models  # noqa: E402

# Import AFTER env pinning (mirrors conftest.py ordering); the engine import
# must come before any module that creates a session.
from database import engine  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Row counts tried for each endpoint: small (realistic board) -> large
# (stress). The harness seeds once per size and measures repeated reads.
MESSAGE_COUNTS = (10, 100, 500)
NOTIFICATION_COUNTS = (10, 100, 500)
FILE_COUNTS = (10, 100, 300)
PAGE_COUNTS = (10, 100, 300)
TASK_COUNTS = (10, 100, 300)

# Warm-up + measurement iterations. Warm-up primes caches (SQLite page cache,
# SQLAlchemy identity map is per-request so it does not leak across calls).
WARMUP_ITERS = 3
MEASURE_ITERS = 20

# ---------------------------------------------------------------------------
# Statement counting (same technique as TA5-1 test_nplus1_regression.py)
# ---------------------------------------------------------------------------


class QueryCounter:
    """Context manager counting SQL statements issued on ``engine``."""

    def __init__(self) -> None:
        self.count = 0

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1

    def __enter__(self) -> QueryCounter:
        sa.event.listen(engine, "before_cursor_execute", self._before)
        return self

    def __exit__(self, *exc) -> None:
        sa.event.remove(engine, "before_cursor_execute", self._before)


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass
class BenchResult:
    endpoint: str
    rows: int
    dialect: str
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    queries: int
    status_code: int
    response_rows: int
    notes: str = ""

    def as_dict(self) -> dict:
        return self.__dict__


@dataclass
class BenchSuite:
    dialect: str
    results: list[BenchResult] = field(default_factory=list)

    def add(self, **kw) -> BenchResult:
        res = BenchResult(dialect=self.dialect, **kw)
        self.results.append(res)
        return res


# ---------------------------------------------------------------------------
# Percentile helper (stdlib only; no numpy dependency allowed)
# ---------------------------------------------------------------------------


def _percentiles(samples_ms: list[float]) -> tuple[float, float, float, float]:
    """Return (p50, p95, min, max) in milliseconds, linear interpolation."""
    ordered = sorted(samples_ms)
    n = len(ordered)

    def _pct(p: float) -> float:
        if n == 1:
            return ordered[0]
        # Linear-interpolation percentile (same definition as numpy default).
        rank = (p / 100.0) * (n - 1)
        lo = int(rank)
        hi = min(lo + 1, n - 1)
        frac = rank - lo
        return ordered[lo] + (ordered[hi] - ordered[lo]) * frac

    return _pct(50.0), _pct(95.0), ordered[0], ordered[-1]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _slug_unique(seed: int) -> str:
    return f"bench-ws-{seed}"


def seed_workspace(db, owner_id: str, seed: int) -> str:
    """Create a workspace + owner membership. Returns workspace id."""
    ws = models.Workspace(
        id=f"ws-{seed}",
        name=f"Bench Workspace {seed}",
        slug=_slug_unique(seed),
        description="benchmark fixture",
    )
    db.add(ws)
    db.flush()
    db.add(
        models.WorkspaceMember(
            workspace_id=ws.id, user_id=owner_id, role="owner"
        )
    )
    db.commit()
    return ws.id


def seed_channel(db, workspace_id: str, created_by: str, name: str) -> str:
    ch = models.Channel(
        workspace_id=workspace_id,
        name=name,
        type="general",
        created_by=created_by,
        is_private=False,
    )
    db.add(ch)
    db.commit()
    return ch.id


def seed_messages(db, channel_id: str, author_id: str, n: int) -> None:
    """Insert n messages with monotonically increasing timestamps so ordering
    is deterministic on both SQLite and Postgres (server-side ``func.now()``
    can tie-break rows at the same instant)."""
    base = datetime.now(UTC)
    for i in range(n):
        stamp = base + timedelta(milliseconds=i)
        db.add(
            models.Message(
                channel_id=channel_id,
                author_id=author_id,
                content=f"bench message {i} " + ("x" * 40),
                created_at=stamp,
                updated_at=stamp,
            )
        )
    db.commit()


def seed_notifications(db, user_id: str, n: int) -> None:
    for i in range(n):
        db.add(
            models.Notification(
                user_id=user_id,
                type="mention",
                title=f"Bench notification {i}",
                content="benchmark fixture",
                read=(i % 3 == 0),
            )
        )
    db.commit()


def seed_files(db, workspace_id: str, uploader_id: str, n: int) -> None:
    """File rows only (no bytes on disk): list_workspace_files reads metadata
    and never touches storage_key content, so rows are representative."""
    for i in range(n):
        db.add(
            models.File(
                workspace_id=workspace_id,
                uploader_id=uploader_id,
                original_name=f"bench-doc-{i}.pdf",
                storage_key=f"bench-{i}-bench-doc-{i}.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
            )
        )
    db.commit()


def seed_pages(db, workspace_id: str, created_by: str, n: int) -> None:
    """n pages: a shallow tree (10 roots, rest children) so both the flat and
    tree shapes of GET /pages are exercised."""
    roots = max(1, n // 10)
    parent_ids: list[str] = []
    for i in range(n):
        parent_id = None
        if i >= roots:
            if not parent_ids:
                parent_ids = [
                    p.id for p in db.query(models.Page.id).filter(
                        models.Page.workspace_id == workspace_id,
                        models.Page.parent_id.is_(None),
                    ).all()
                ]
            parent_id = parent_ids[i % len(parent_ids)] if parent_ids else None
        db.add(
            models.Page(
                workspace_id=workspace_id,
                parent_id=parent_id,
                title=f"Bench Page {i}",
                slug=f"bench-page-{i}",
                content="benchmark fixture content",
                created_by=created_by,
                updated_by=created_by,
            )
        )
    db.commit()


def seed_project_with_tasks(db, workspace_id: str, owner_id: str, n: int) -> str:
    """Create one project + n tasks assigned to owner (drives /users/me/tasks
    and /projects/{id}/tasks)."""
    project = models.Project(
        workspace_id=workspace_id, owner_id=owner_id, name="Bench Project"
    )
    db.add(project)
    db.flush()
    for i in range(n):
        db.add(
            models.Task(
                project_id=project.id,
                assignee_id=owner_id,
                title=f"Bench task {i}",
                status="todo",
                priority="medium",
                position=float(i),
            )
        )
    db.commit()
    return project.id


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def measure(
    client: TestClient,
    method: str,
    url: str,
    rows: int,
    suite: BenchSuite,
    notes: str = "",
) -> BenchResult:
    """Warm up, then time MEASURE_ITERS requests; count statements on the
    final timed request (query count is per-request and stable)."""
    for _ in range(WARMUP_ITERS):
        resp = client.request(method, url)
        if resp.status_code != 200:
            break
    samples: list[float] = []
    last_status = 0
    last_rows = 0
    last_queries = 0
    for _ in range(MEASURE_ITERS):
        with QueryCounter() as qc:
            t0 = time.perf_counter()
            resp = client.request(method, url)
            t1 = time.perf_counter()
        last_status = resp.status_code
        last_queries = qc.count
        if last_status == 200 and isinstance(resp.json(), list):
            last_rows = len(resp.json())
        samples.append((t1 - t0) * 1000.0)
    p50, p95, mn, mx = _percentiles(samples)
    return suite.add(
        endpoint=f"{method} {url.split('?')[0]}",
        rows=rows,
        p50_ms=round(p50, 3),
        p95_ms=round(p95, 3),
        min_ms=round(mn, 3),
        max_ms=round(mx, 3),
        queries=last_queries,
        status_code=last_status,
        response_rows=last_rows,
        notes=notes,
    )


def measure_parametrized(
    client: TestClient,
    method: str,
    url_tmpl: str,
    ids: list[str],
    rows: int,
    suite: BenchSuite,
    notes: str = "",
) -> BenchResult:
    """Measure one URL per fixture id (avoids the per-request identity-map
    cache hiding the cost of the first row fetch)."""
    samples: list[float] = []
    last_status, last_rows, last_queries = 0, 0, 0
    iters = max(1, MEASURE_ITERS // max(1, len(ids)))
    for fid in ids:
        url = url_tmpl.format(fid=fid)
        for _ in range(WARMUP_ITERS):
            client.request(method, url)
        for _ in range(iters):
            with QueryCounter() as qc:
                t0 = time.perf_counter()
                resp = client.request(method, url)
                t1 = time.perf_counter()
            last_status = resp.status_code
            last_queries = qc.count
            if last_status == 200 and isinstance(resp.json(), list):
                last_rows = len(resp.json())
            samples.append((t1 - t0) * 1000.0)
    p50, p95, mn, mx = _percentiles(samples)
    return suite.add(
        endpoint=f"{method} {url_tmpl.split('?')[0]}",
        rows=rows,
        p50_ms=round(p50, 3),
        p95_ms=round(p95, 3),
        min_ms=round(mn, 3),
        max_ms=round(mx, 3),
        queries=last_queries,
        status_code=last_status,
        response_rows=last_rows,
        notes=notes,
    )
