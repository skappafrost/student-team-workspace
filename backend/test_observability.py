"""TA6-1: slow-query logging, 5xx counter, /readyz vs /healthz (real JWT only).

Privacy invariants checked here: bound parameters and client tokens never
reach the new log lines, and the readiness report never leaks the
connection string or exception text.

Log capture uses dedicated handlers on the ``stw.requests``/``stw.db``
loggers rather than pytest's ``caplog``: earlier modules (test_models.py)
run ``alembic upgrade``, whose ``fileConfig`` call replaces root handlers and
disables pre-existing loggers, so caplog is unreliable in a full-suite pass.
The ``stw_capture`` fixture re-enables the loggers and listens on them
directly, keeping these assertions hermetic in either order.
"""

import logging

import pytest
from sqlalchemy import text

import logging_mw
from conftest import clear_auth
from database import engine

FAKE = "FAKE-SECRET-TOKEN-never-log-1a2b3c4d5e6f"


class _ListHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self.messages: list[str] = []

    def emit(self, record):
        try:
            self.messages.append(record.getMessage())
        except Exception:
            self.handleError(record)


@pytest.fixture
def stw_capture():
    handlers = {}
    for name in ("stw.requests", "stw.db"):
        lg = logging.getLogger(name)
        lg.disabled = False
        h = _ListHandler(level=logging.WARNING)
        lg.addHandler(h)
        handlers[name] = h
    yield handlers
    for name, h in handlers.items():
        logging.getLogger(name).removeHandler(h)


@pytest.fixture
def zero_threshold(monkeypatch):
    """Force every statement to count as slow (threshold 0 = always log)."""
    monkeypatch.setattr(logging_mw.settings, "slow_query_threshold_ms", 0.0)


def _slow_lines(capture):
    return [m for m in capture["stw.db"].messages if "slow_query" in m]


# ---------------------------------------------------------------------------
# Slow-query logging
# ---------------------------------------------------------------------------

def test_slow_query_triggers_warning(zero_threshold, stw_capture):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1 AS obs_probe"))
    lines = [m for m in _slow_lines(stw_capture) if "obs_probe" in m]
    assert lines, "threshold 0 must log every statement as slow"
    assert "stmt=SELECT 1 AS obs_probe" in lines[0]
    assert "ms" in lines[0]


def test_fast_query_not_logged(stw_capture):
    # Default threshold (200ms) leaves a sub-millisecond SELECT untouched.
    with engine.connect() as conn:
        conn.execute(text("SELECT 1 AS obs_fast"))
    assert not [m for m in _slow_lines(stw_capture) if "obs_fast" in m]


def test_fingerprint_masks_literals():
    fp = logging_mw._fingerprint("SELECT * FROM users WHERE name = 'alice'")
    assert "alice" not in fp
    assert "'?'" in fp


def test_bound_params_never_logged(zero_threshold, stw_capture):
    with engine.connect() as conn:
        conn.execute(text("SELECT :p AS obs_param"), {"p": "SUPERSECRET-VALUE-42"})
    joined = "\n".join(_slow_lines(stw_capture))
    assert "obs_param" in joined
    assert "SUPERSECRET-VALUE-42" not in joined


# ---------------------------------------------------------------------------
# 5xx counter + access-log upgrade
# ---------------------------------------------------------------------------

@pytest.fixture
def boom_routes():
    """Temporarily mount a 500-returning and a crashing GET route."""
    from fastapi.responses import JSONResponse

    from app import app as fastapi_app

    def _five():
        return JSONResponse({"detail": "boom"}, status_code=500)

    def _crash():
        raise RuntimeError("obs crash")

    fastapi_app.get("/_obs_five")(_five)
    fastapi_app.get("/_obs_crash")(_crash)
    routes = fastapi_app.router.routes[-2:]
    yield
    for r in routes:
        fastapi_app.router.routes.remove(r)


def test_5xx_counted_and_warned(client, boom_routes, stw_capture):
    clear_auth(client)
    before = client.get("/healthz").json()["errors_5xx"]

    resp = client.get("/_obs_five", headers={"Authorization": f"Bearer {FAKE}"})
    assert resp.status_code == 500

    after = client.get("/healthz").json()["errors_5xx"]
    assert after == before + 1, "the 5xx must bump the counter exposed on /healthz"

    warn_lines = [m for m in stw_capture["stw.requests"].messages if "/_obs_five" in m]
    assert warn_lines, "5xx access lines are upgraded to WARNING"
    assert "err5xx=" in warn_lines[-1]
    assert FAKE not in "\n".join(stw_capture["stw.requests"].messages), (
        "token material must never reach the new log line"
    )


def test_unhandled_crash_counts_as_5xx(boom_routes, stw_capture):
    from fastapi.testclient import TestClient

    from app import app as fastapi_app

    raw = TestClient(fastapi_app, raise_server_exceptions=False)
    before = logging_mw.error_5xx_count()
    resp = raw.get("/_obs_crash")
    assert resp.status_code == 500
    assert logging_mw.error_5xx_count() == before + 1
    assert any("/_obs_crash" in m for m in stw_capture["stw.requests"].messages)


# ---------------------------------------------------------------------------
# /readyz vs /healthz
# ---------------------------------------------------------------------------

_ALEMBIC_VERSION_DDL = (
    "CREATE TABLE alembic_version ("
    "version_num VARCHAR(32) NOT NULL, "
    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
)


def _drop_version_table():
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def _stamp(revision):
    with engine.begin() as conn:
        conn.execute(text(_ALEMBIC_VERSION_DDL))
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": revision}
        )


def test_readyz_503_when_schema_unstamped(client):
    # conftest builds tables via create_all, never through alembic -> not ready.
    clear_auth(client)
    _drop_version_table()
    try:
        h = client.get("/healthz")
        assert h.status_code == 200 and h.json()["status"] == "ok"

        r = client.get("/readyz")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "not_ready"
        assert body["db"] is True, "the DB is reachable; only the stamp is missing"
        assert body["schema_current"] is False
        assert body["alembic_applied"] == []
        heads = logging_mw.alembic_heads()
        assert len(heads) == 1, "alembic discipline: exactly one declared head"
        assert body["alembic_heads"] == heads
    finally:
        _drop_version_table()


def test_readyz_200_when_stamped_at_head(client):
    clear_auth(client)
    heads = logging_mw.alembic_heads()
    assert len(heads) == 1
    _drop_version_table()
    _stamp(heads[0])
    try:
        r = client.get("/readyz")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["schema_current"] is True
        assert body["alembic_applied"] == heads
        blob = r.text.lower()
        assert "sqlite:///" not in blob and "database_url" not in blob
        assert "password" not in blob
    finally:
        _drop_version_table()


def test_readyz_503_on_stale_head(client):
    clear_auth(client)
    _drop_version_table()
    _stamp("deadbeef0000")
    try:
        r = client.get("/readyz")
        assert r.status_code == 503
        body = r.json()
        assert body["db"] is True
        assert body["schema_current"] is False
        assert body["alembic_applied"] == ["deadbeef0000"]
    finally:
        _drop_version_table()
