"""The demo-pack loader must survive the app's own rate limiter.

``scripts/demo-packs/load-pack.py`` posts every task in the pack as one identity
into the ``tasks`` write bucket, and ``backend/rate_limit.py`` caps that bucket
at ``(120, 60)`` — the shipped pack has 200 tasks, so a load is *expected* to be
throttled. Before the loader knew that, a documented command exited 1 part-way
through (measured: 120 accepted task writes, then
``ERROR: create task 'Demo pit-crew checklist #21' failed: HTTP 429``) and the CI
job that nominally covers the pack only parses JSON, so nothing ever ran it.

These tests drive the loader's own request loop — ``main()`` over the real
``api()`` retry path, with only the one-call transport replaced — against a
``TestClient`` of the real app (same middleware, same buckets) with a deliberately
low write limit, and assert the pack still lands whole.

CLOCK: the limiter's sliding window and the loader's back-off both use wall time,
so a test that waited for real would be slow and flaky for no extra information.
``rate_limit.time`` and the loader's ``time`` are replaced by one fake clock whose
``sleep`` advances ``monotonic`` instantly. The limiter logic, the ``Retry-After``
header the app sends and the loader's reading of it are all still exercised; only
the waiting is simulated. The recorded sleep sequence is asserted against the
recorded ``Retry-After`` sequence, so "it waited what the server asked" is checked,
not assumed.
"""

import importlib.util
import json
import re
import sys
import time as real_time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models
import rate_limit
from app import app
from database import get_db

BACKEND_DIR = Path(__file__).resolve().parent
LOADER_PATH = BACKEND_DIR.parent / "scripts" / "demo-packs" / "load-pack.py"
DB_URL = "sqlite:///./test_stw_demo_pack.db"
BASE = "http://testserver"
PASSWORD = "Loader-Test-1"


def load_loader_module():
    """Import load-pack.py from disk (its ``__main__`` guard keeps main() asleep)."""
    spec = importlib.util.spec_from_file_location("load_pack_under_test", LOADER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeClock:
    """``time`` for the limiter and the loader, advanced by ``sleep`` instead of by waiting."""

    def __init__(self):
        self.now = 10_000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, secs: float) -> None:
        self.slept.append(secs)
        self.now += secs

    def __getattr__(self, name):
        return getattr(real_time, name)


def mini_pack(tmp_path: Path, *, users=2, tasks=6, messages=3, pages=2) -> Path:
    """A pack shaped like ``busy-workspace.json`` but small enough to load in a test."""
    pack = {
        "meta": {"generator": "test", "seed": 1, "generated_at": "2026-01-01T00:00:00Z"},
        "workspace": {
            "name": "Loader Test Workspace",
            "slug": f"loader-test-{tmp_path.name}",
            "description": "Seeded by test_demo_pack_loader.py",
        },
        "users": [
            {
                "display_name": f"Loader User {i}",
                "email": f"loader-u{i}@example.com",
                "password": PASSWORD,
                "role": "member",
            }
            for i in range(users)
        ],
        "projects": [
            {
                "key": "p1",
                "name": "Loader Project",
                "description": "one board",
                "tasks": [
                    {
                        "title": f"Loader task {i:02d}",
                        "description": "seeded",
                        "status": "todo",
                        "priority": "medium",
                        "assignee_index": i % users,
                        "position": float(i),
                    }
                    for i in range(tasks)
                ],
            }
        ],
        "channels": [
            {
                "name": "loader-general",
                "type": "general",
                "topic": "chat",
                "messages": [
                    {"author_index": i % (users + 1), "content": f"loader message {i}"}
                    for i in range(messages)
                ],
            }
        ],
        "pages": [
            {"title": "Loader Root Page", "slug": "loader-root", "parent_slug": None, "content": "# hi"},
            {"title": "Loader Child Page", "slug": "loader-child", "parent_slug": "loader-root", "content": "# there"},
        ][:pages],
    }
    path = tmp_path / "mini-pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    return path


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(DB_URL, echo=False, future=True)
    TestingSessionLocal = sessionmaker(autoflush=False, bind=engine)
    models.Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    # Own engine, own tables: the shared conftest fixtures drop_all() the
    # process-wide test_stw.db that other agents' runs are writing into.
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield db
    finally:
        app.dependency_overrides.clear()
        db.close()
        models.Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(rate_limit, "time", fake)
    yield fake


class LoaderRun:
    """Runs the loader's own ``main()`` over a TestClient transport."""

    def __init__(self, mod, clock, monkeypatch):
        self.mod = mod
        self.clock = clock
        self.calls: list[dict] = []
        monkeypatch.setattr(mod, "time", clock)
        monkeypatch.setattr(mod, "_request", self._request)

    def _request(self, method, url, token=None, payload=None, timeout=15.0):
        path = url[len(BASE):] or "/"
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # A fresh client per call: the loader's urllib transport keeps no cookies,
        # and `_token_from_request` prefers the session_token cookie over the
        # Bearer header, so one shared client would re-identify every request.
        resp = TestClient(app, raise_server_exceptions=False).request(
            method, path, headers=headers, json=payload
        )
        try:
            body = resp.json()
        except Exception:
            body = None
        header = resp.headers.get("retry-after")
        try:
            retry_after = float(header) if header else 0.0
        except (TypeError, ValueError):
            retry_after = 0.0
        self.calls.append(
            {
                "method": method,
                "path": path,
                "status": resp.status_code,
                "group": rate_limit._write_group(method, path),
                "retry_after": retry_after,
                "payload": json.dumps(payload, sort_keys=True) if payload else "",
            }
        )
        return resp.status_code, body, retry_after

    def run(self, pack_path: Path, monkeypatch, *, max_wait=1e6):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                str(LOADER_PATH),
                "--api", BASE,
                "--email", "loader-admin@example.com",
                "--password", PASSWORD,
                "--pack", str(pack_path),
                "--max-retry-wait", str(max_wait),
            ],
        )
        code = 0
        try:
            self.mod.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return code

    def count(self, predicate) -> int:
        return sum(1 for c in self.calls if predicate(c))


def write_limit(monkeypatch, limit):
    monkeypatch.setattr(rate_limit, "DEFAULT_WRITE_LIMIT", limit)


# ---------------------------------------------------------------------------
# REGRESSION — a rate-limited load still writes everything
# ---------------------------------------------------------------------------


def test_pack_loads_under_a_deliberately_low_write_limit(db_session, clock, monkeypatch, tmp_path, capsys):
    """Every 429 is waited out and re-sent; no task, message or page is lost."""
    write_limit(monkeypatch, (2, 60))  # 2 writes per identity per route group per minute
    rate_limit.reset()
    run = LoaderRun(load_loader_module(), clock, monkeypatch)
    code = run.run(mini_pack(tmp_path, tasks=6, messages=3, pages=2, users=2), monkeypatch)
    out = capsys.readouterr().out

    denials = [c for c in run.calls if c["status"] == 429]
    print(
        "MEASURE after(write limit 2/60, pack=6 tasks): "
        f"exit={code} requests={len(run.calls)} 429s={len(denials)} "
        f"retries={run.mod.STATS['retried']} slept={clock.slept}"
    )
    assert code == 0, out + f" calls={[c['status'] for c in run.calls]}"
    assert denials, "the low limit never bit, so this test would not have caught the old failure"

    # The loader waited exactly what the server asked, in order, for every denial.
    assert clock.slept == [c["retry_after"] for c in denials]
    assert all(s > 0 for s in clock.slept), clock.slept

    # Nothing was lost: every write the pack holds exists once in the database.
    for table, want in (("tasks", 6), ("messages", 3), ("pages", 2), ("workspace_members", 3)):
        got = db_session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        assert got == want, f"{table}: loaded {got}, pack holds {want}"

    task_posts = [c for c in run.calls if c["group"] == "tasks"]
    assert sum(1 for c in task_posts if c["status"] == 201) == 6, task_posts
    assert all(c["payload"] for c in task_posts)

    assert "counts: " in out
    assert json.loads(out.split("counts: ")[1].splitlines()[0])["tasks"] == 6
    assert "OK: demo pack verified" in out


def test_the_loader_states_its_request_count_and_waits_it_out(db_session, clock, monkeypatch, tmp_path, capsys):
    """The operator-facing promise: the plan says what will happen, the run agrees."""
    write_limit(monkeypatch, (2, 60))
    rate_limit.reset()
    mod = load_loader_module()
    run = LoaderRun(mod, clock, monkeypatch)
    pack = mini_pack(tmp_path, tasks=6, messages=3, pages=2, users=2)
    code = run.run(pack, monkeypatch)
    out = capsys.readouterr().out

    plan = re.search(r"plan: (\d+) requests", out)
    assert plan, out
    # 30 operations: 6 auth, 1 workspace, 2 invites + 2 accepts, 1 project, 6 tasks,
    # 1 channel, 3 messages, 2 pages, then 6 re-reads. The plan counts what the pack
    # asks the API to do; a 429 adds a re-send on top, so the wire count is the plan
    # plus the retries the run reports.
    assert int(plan.group(1)) == 30
    assert len(run.calls) == 30 + run.mod.STATS["retried"], (len(run.calls), run.mod.STATS)

    summary = re.search(r"run: requests=(\d+) rate-limit retries=(\d+) waited=([\d.]+)s", out)
    assert summary, out
    assert int(summary.group(1)) == len(run.calls)
    assert int(summary.group(2)) == run.mod.STATS["retried"] == len(clock.slept)
    assert float(summary.group(3)) == sum(clock.slept)
    assert code == 0


def test_an_unthrottled_load_makes_exactly_the_planned_requests_and_nothing_more(
    db_session, clock, monkeypatch, tmp_path, capsys
):
    """Control: the retry loop is invisible when the server does not throttle."""
    write_limit(monkeypatch, (500, 60))
    rate_limit.reset()
    run = LoaderRun(load_loader_module(), clock, monkeypatch)
    code = run.run(mini_pack(tmp_path, tasks=6, messages=3, pages=2, users=2), monkeypatch)
    out = capsys.readouterr().out
    print(
        f"MEASURE control(500/60 write limit, pack=6 tasks): exit={code} "
        f"requests={len(run.calls)} 429s=0 slept={clock.slept}"
    )
    assert code == 0
    assert clock.slept == []
    assert run.mod.STATS["retried"] == 0
    assert not any(c["status"] == 429 for c in run.calls)
    assert int(re.search(r"plan: (\d+) requests", out).group(1)) == len(run.calls)
    assert db_session.execute(text("SELECT count(*) FROM tasks")).scalar_one() == 6


# ---------------------------------------------------------------------------
# CONTROLS — the retry path is for 429 and for nothing else
# ---------------------------------------------------------------------------


def test_a_non_429_refusal_is_still_fatal_and_never_retried(
    db_session, clock, monkeypatch, tmp_path, capsys
):
    """Only a rate limit is waited out; a 403 is still the error it always was."""
    write_limit(monkeypatch, (500, 60))
    rate_limit.reset()
    mod = load_loader_module()
    run = LoaderRun(mod, clock, monkeypatch)
    original = run._request
    poisoned: list[int] = []

    def _request(method, url, token=None, payload=None, timeout=15.0):
        # The refusal is simulated *instead of* sent, so the row is never written
        # and the count below really does say "the loader stopped here".
        if url.endswith("/tasks") and method == "POST" and not poisoned:
            poisoned.append(201)
            run.calls.append({"method": method, "path": url, "status": 403, "group": "tasks",
                              "retry_after": 0.0, "payload": ""})
            return 403, {"detail": "simulated refusal"}, 0.0
        return original(method, url, token, payload, timeout)

    monkeypatch.setattr(mod, "_request", _request)
    code = run.run(mini_pack(tmp_path, tasks=6), monkeypatch)
    captured = capsys.readouterr()
    print(f"MEASURE control(403 on the first task POST): exit={code} slept={clock.slept}")
    assert code == 1, captured.out
    assert "create task 'Loader task 00' failed: HTTP 403" in captured.err
    assert clock.slept == [], "a 403 must not be waited out"
    assert run.mod.STATS["retried"] == 0
    assert db_session.execute(text("SELECT count(*) FROM tasks")).scalar_one() == 0


def test_a_server_that_limits_forever_gives_up_instead_of_hanging(
    db_session, clock, monkeypatch, tmp_path, capsys
):
    """The back-off is bounded, so a misconfigured target cannot hang the loader."""
    write_limit(monkeypatch, (500, 60))
    rate_limit.reset()
    mod = load_loader_module()
    run = LoaderRun(mod, clock, monkeypatch)

    def _always_limited(method, url, token=None, payload=None, timeout=15.0):
        run.calls.append({"method": method, "path": url, "status": 429, "group": None,
                          "retry_after": 5.0, "payload": ""})
        return 429, {"detail": "Rate limit exceeded for write:tasks"}, 5.0

    monkeypatch.setattr(mod, "_request", _always_limited)
    code = run.run(mini_pack(tmp_path, tasks=1), monkeypatch, max_wait=25.0)
    captured = capsys.readouterr()
    print(f"MEASURE control(permanent 429, --max-retry-wait=25): exit={code} slept={clock.slept}")
    assert code == 1
    # 5 waits of the 5s the server asked for, then the 25s budget is spent.
    assert clock.slept == [5.0] * 5, clock.slept
    assert "refused after" in captured.err
    assert "raise --max-retry-wait or start the server with RATELIMIT_ENABLED=0" in captured.err


def test_the_limiter_itself_is_untouched_by_the_loader(db_session, clock, monkeypatch, tmp_path):
    """The fix is loader-side: the app still denies at the same point for everyone else.

    ``ENVIRONMENT=dev`` must not switch the limiter off either — only
    ``RATELIMIT_ENABLED=0`` does, which is why the loader has to survive 429
    rather than assume a server with no limits.
    """
    write_limit(monkeypatch, (3, 60))
    rate_limit.reset()
    from app import create_access_token

    tok = create_access_token("loader-other-user")
    statuses = [
        TestClient(app, raise_server_exceptions=False).post(
            "/workspaces/loader-nonexistent/pages",
            headers={"Authorization": f"Bearer {tok}"},
            json={"title": f"t{i}", "slug": f"t{i}"},
        ).status_code
        for i in range(5)
    ]
    print(f"MEASURE control(other traffic, limit 3/60): statuses={statuses}")
    assert statuses[:3] == [404, 404, 404], statuses  # the route's own answer, untouched
    assert statuses[3:] == [429, 429], (
        "the limiter was weakened for traffic that is not the loader"
    )

    monkeypatch.setenv("RATELIMIT_ENABLED", "0")
    rate_limit.reset()
    off = TestClient(app, raise_server_exceptions=False).post(
        "/workspaces/loader-nonexistent/pages",
        headers={"Authorization": f"Bearer {tok}"},
        json={"title": "off", "slug": "off"},
    ).status_code
    assert off != 429
    monkeypatch.delenv("RATELIMIT_ENABLED", raising=False)
