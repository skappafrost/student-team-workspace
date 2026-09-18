#!/usr/bin/env python
"""TA6-2 entry point: seed fixtures, measure hot read paths, write results.

Usage (from backend/):

    python bench/run_bench.py                 # local SQLite, writes bench/results.json
    python bench/run_bench.py --json bench/results.json
    DATABASE_URL=postgresql://user:pw@host/db python bench/run_bench.py

This script is deliberately NOT a pytest module: it lives under bench/, which
pytest never collects (no test_*/test_* functions, and run_bench.py is a
__main__ script). ``make bench`` is the documented opt-in entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Pin DATABASE_URL BEFORE importing app/engine (mirrors conftest.py ordering).
BENCH_DB = os.environ.get("STW_BENCH_DB")
if BENCH_DB:
    os.environ.setdefault("DATABASE_URL", BENCH_DB)
os.environ.setdefault("DATABASE_URL", "sqlite:///bench_stw.db")
os.environ.setdefault("ENVIRONMENT", "test")

# Keep uploads off the real repo tree; list endpoints never read disk anyway.
os.environ.setdefault("STW_UPLOAD_DIR", str(Path(__file__).resolve().parent / "uploads"))

# Make ``bench`` importable when run as a plain script (``python bench/run_bench.py``).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import sessionmaker  # noqa: E402

import models  # noqa: E402
from app import app, create_access_token  # noqa: E402
from bench import (  # noqa: E402
    MEASURE_ITERS,
    WARMUP_ITERS,
    BenchSuite,
    measure,
    seed_channel,
    seed_files,
    seed_messages,
    seed_notifications,
    seed_pages,
    seed_project_with_tasks,
    seed_workspace,
)
from database import Base, engine, get_db  # noqa: E402

OWNER = "bench-owner"


def _dialect_name() -> str:
    url = engine.url
    return url.get_dialect().name if hasattr(url, "get_dialect") else url.drivername


def reset_schema() -> None:
    """Fresh schema for the benchmark DB (drop + create)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def bench_client(session_factory) -> object:
    """TestClient bound to the benchmark session (real JWT auth)."""
    from fastapi.testclient import TestClient

    def _override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def make_owner(db) -> str:
    user = models.User(id=OWNER, email="bench@example.com", display_name="Bench Owner")
    db.add(user)
    db.commit()
    return OWNER


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default="bench/results.json", help="output JSON path")
    ap.add_argument(
        "--iters", type=int, default=MEASURE_ITERS, help="timed requests per endpoint"
    )
    ap.add_argument(
        "--quick", action="store_true", help="small seed counts, for CI smoke runs"
    )
    args = ap.parse_args(argv)

    import bench as bench_mod

    if args.iters != MEASURE_ITERS:
        bench_mod.MEASURE_ITERS = args.iters
    if args.quick:
        bench_mod.MESSAGE_COUNTS = (10, 50)
        bench_mod.NOTIFICATION_COUNTS = (10, 50)
        bench_mod.FILE_COUNTS = (10, 50)
        bench_mod.PAGE_COUNTS = (10, 50)
        bench_mod.TASK_COUNTS = (10, 50)

    dialect = _dialect_name()
    print(f"[bench] dialect={dialect} db={engine.url.database or engine.url}")
    print(f"[bench] warmup={WARMUP_ITERS} iters={bench_mod.MEASURE_ITERS}")

    reset_schema()
    session_factory = sessionmaker(bind=engine, autoflush=False)
    client = bench_client(session_factory)
    token = {  # noqa: F841  (kept for header-level debugging)
        "Authorization": f"Bearer {create_access_token(OWNER)}"
    }
    # Global default auth header; individual calls may override.
    client.headers.update(token)

    db = session_factory()
    try:
        make_owner(db)
    finally:
        db.close()

    suite = BenchSuite(dialect=dialect)
    t_start = time.perf_counter()

    # ------------------------------------------------------------------
    # Fixture set: one workspace per (endpoint, size) so sizes never share
    # rows and each measurement reads exactly the seeded row count.
    # ------------------------------------------------------------------
    ws_seq = 0
    for size in bench_mod.MESSAGE_COUNTS:
        ws_seq += 1
        db = session_factory()
        try:
            ws_id = seed_workspace(db, OWNER, ws_seq)
            ch_id = seed_channel(db, ws_id, OWNER, f"bench-ch-{ws_seq}")
            seed_messages(db, ch_id, OWNER, size)
        finally:
            db.close()
        measure(
            client,
            "GET",
            f"/channels/{ch_id}/messages",
            rows=size,
            suite=suite,
            notes="paginated message list (TA5-1 selectinload fix)",
        )
        print(f"[bench] messages n={size} done")

    for size in bench_mod.NOTIFICATION_COUNTS:
        ws_seq += 1
        db = session_factory()
        try:
            ws_id = seed_workspace(db, OWNER, ws_seq)
            seed_notifications(db, OWNER, size)
        finally:
            db.close()
        measure(
            client,
            "GET",
            "/notifications",
            rows=size,
            suite=suite,
            notes="user notification inbox",
        )
        print(f"[bench] notifications n={size} done")

    for size in bench_mod.FILE_COUNTS:
        ws_seq += 1
        db = session_factory()
        try:
            ws_id = seed_workspace(db, OWNER, ws_seq)
            seed_files(db, ws_id, OWNER, size)
        finally:
            db.close()
        measure(
            client,
            "GET",
            f"/workspaces/{ws_id}/files",
            rows=size,
            suite=suite,
            notes="workspace file metadata list",
        )
        print(f"[bench] files n={size} done")

    for size in bench_mod.PAGE_COUNTS:
        ws_seq += 1
        db = session_factory()
        try:
            ws_id = seed_workspace(db, OWNER, ws_seq)
            seed_pages(db, ws_id, OWNER, size)
        finally:
            db.close()
        measure(
            client,
            "GET",
            f"/workspaces/{ws_id}/pages",
            rows=size,
            suite=suite,
            notes="wiki tree (recursive build in endpoint)",
        )
        print(f"[bench] pages tree n={size} done")
        db = session_factory()
        try:
            measure(
                client,
                "GET",
                f"/workspaces/{ws_id}/pages?flat=true",
                rows=size,
                suite=suite,
                notes="wiki flat list",
            )
        finally:
            db.close()
        print(f"[bench] pages flat n={size} done")

    for size in bench_mod.TASK_COUNTS:
        ws_seq += 1
        db = session_factory()
        try:
            ws_id = seed_workspace(db, OWNER, ws_seq)
            project_id = seed_project_with_tasks(db, ws_id, OWNER, size)
        finally:
            db.close()
        measure(
            client,
            "GET",
            f"/projects/{project_id}/tasks",
            rows=size,
            suite=suite,
            notes="project task board (kanban column source)",
        )
        print(f"[bench] project tasks n={size} done")
        measure(
            client,
            "GET",
            "/users/me/tasks",
            rows=size,
            suite=suite,
            notes="cross-workspace my-tasks aggregation",
        )
        print(f"[bench] my tasks n={size} done")

    t_total = time.perf_counter() - t_start
    app.dependency_overrides.clear()

    payload = {
        "dialect": dialect,
        "database": str(engine.url),
        "warmup_iters": WARMUP_ITERS,
        "measure_iters": bench_mod.MEASURE_ITERS,
        "seed_counts": {
            "messages": list(bench_mod.MESSAGE_COUNTS),
            "notifications": list(bench_mod.NOTIFICATION_COUNTS),
            "files": list(bench_mod.FILE_COUNTS),
            "pages": list(bench_mod.PAGE_COUNTS),
            "tasks": list(bench_mod.TASK_COUNTS),
        },
        "total_seconds": round(t_total, 2),
        "results": [r.as_dict() for r in suite.results],
    }
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"[bench] wrote {out} ({len(suite.results)} measurements in {t_total:.1f}s)")

    # Human-readable summary table.
    print("\nendpoint                                    rows   p50_ms   p95_ms  queries  status")
    print("-" * 92)
    for r in suite.results:
        print(
            f"{r.endpoint:<42} {r.rows:>6} {r.p50_ms:>8.2f} {r.p95_ms:>8.2f} "
            f"{r.queries:>8} {r.status_code:>7}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
