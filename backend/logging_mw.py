"""Request logging middleware + DB-backed health readout (T3-B03).

Single home for request observability so ``app.py`` wiring stays within its
3-added-line budget (one import, one ``add_middleware``, one
``register_healthz`` call):

- :class:`RequestLoggingMiddleware` attaches an ``X-Request-Id`` to every
  response (honouring an incoming one) and logs exactly ONE info line per
  request: ``METHOD path status ms user=... req=...``.
- Privacy: only ``request.url.path`` is logged (never the query string --
  ``session_token`` travels there for WebSockets), and headers/cookies are
  never logged. The user id is recovered from the JWT ``sub`` claim via an
  unverified base64 decode so the token string itself never touches the log.
- :func:`db_latency_ms` runs ``SELECT 1`` and returns the round-trip in
  milliseconds (``None`` when the DB is unreachable). Failures intentionally
  surface no exception text/connection string -- never leaks creds.
- :func:`register_healthz` mounts ``GET /healthz`` (``/health`` stays exactly
  ``{"status": "ok"}`` for backward compatibility).

TA6-1 adds the rest of the stage-6 observability set, same privacy rules:

- :func:`attach_slow_query_logging` (called from ``database._make_engine``,
  so it also covers engines rebound by ``set_db_url``): statements at/over
  ``SLOW_QUERY_THRESHOLD_MS`` (default 200) log a ``slow_query`` WARNING
  with a whitespace-collapsed, literal-masked fingerprint -- never params.
- A process-global 5xx counter; those access lines move to WARNING.
- ``register_healthz`` also mounts ``GET /readyz``: 200 only while the DB
  answers ``SELECT 1`` AND ``alembic_version`` equals the single declared
  head, else 503. The report holds only booleans, latencies, revision ids.
"""

import base64
import json
import logging
import re
import time
import uuid
from pathlib import Path

from sqlalchemy import event
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from config import settings

logger = logging.getLogger("stw.requests")
_slow_logger = logging.getLogger("stw.db")


def _sanitize_request_id(value: str) -> str:
    """Strip log-injection characters and cap length of a client request id."""
    return value.replace("\r", "").replace("\n", "").strip()[:64]


def _token_from_request(request: Request) -> str | None:
    """Best-effort session token lookup (cookie first, then Bearer header)."""
    token = request.cookies.get("session_token")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    return None


def _user_id_from_token(token: str) -> str | None:
    """Recover the JWT ``sub`` without verifying (never logs the token)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        sub = payload.get("sub")
        return sub if isinstance(sub, str) and sub else None
    except Exception:
        return None


def request_user_id(request: Request) -> str:
    """User id for the log line, ``-`` when anonymous/undecodable."""
    try:
        token = _token_from_request(request)
    except Exception:
        return "-"
    if not token:
        return "-"
    return _user_id_from_token(token) or "-"


def _bump_5xx() -> int:
    """Record a server error; return the new process-wide 5xx count."""
    global _error_5xx_count
    _error_5xx_count += 1
    return _error_5xx_count


_error_5xx_count = 0


def error_5xx_count() -> int:
    """Process-wide count of responses/crashes that ended in 5xx."""
    return _error_5xx_count


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach ``X-Request-Id`` and log one safe line per request (TA6-1:
    5xx lines are WARNING and bump the shared 5xx counter)."""

    def _log(self, request, request_id, status, elapsed_ms):
        args = (request.method, request.url.path, status, elapsed_ms,
                request_user_id(request), request_id)
        if status >= 500:
            logger.warning("%s %s %s %.1fms user=%s req=%s err5xx=%d",
                           *args, _bump_5xx())
        else:
            logger.info("%s %s %s %.1fms user=%s req=%s", *args)

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("X-Request-Id", "")
        request_id = _sanitize_request_id(incoming) or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self._log(request, request_id, 500, (time.perf_counter() - start) * 1000)
            raise
        self._log(request, request_id, response.status_code,
                  (time.perf_counter() - start) * 1000)
        response.headers["X-Request-Id"] = request_id
        return response


# ---------------------------------------------------------------------------
# Slow-query logging (TA6-1)
# ---------------------------------------------------------------------------

_MAX_STMT_CHARS = 180
_QUOTED_LITERAL_RE = re.compile(r"'[^']*'")


def _fingerprint(statement: str) -> str:
    """One-line, value-free view of a SQL statement.

    Collapses whitespace, masks any inlined single-quoted literals with
    ``'?'`` and caps length. Bound parameters are never part of the
    statement text SQLAlchemy hands us, so raw values cannot leak.
    """
    collapsed = _QUOTED_LITERAL_RE.sub("'?'", " ".join(statement.split()))
    return collapsed[:_MAX_STMT_CHARS]


def attach_slow_query_logging(engine) -> None:
    """Log statements slower than ``settings.slow_query_threshold_ms``.

    Called by ``database._make_engine`` for every engine the app builds.
    The hot path per statement is one dict set/pop plus a float compare --
    nothing heavier, no new dependencies.
    """

    @event.listens_for(engine, "before_cursor_execute")
    def _qstart(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("stw_qtimes", {})[_stmt_key(context)] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _qend(conn, cursor, statement, parameters, context, executemany):
        starts = conn.info.get("stw_qtimes")
        if not starts:
            return
        start = starts.pop(_stmt_key(context), None)
        if len(starts) > 256:  # statements that errored never pop; bound the map
            starts.clear()
        if start is None:
            return
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms >= settings.slow_query_threshold_ms:
            _slow_logger.warning(
                "slow_query %.1fms stmt=%s", elapsed_ms, _fingerprint(statement)
            )


def _stmt_key(context) -> str:
    """In-flight statement key; nested executions must not clobber each other."""
    return "root" if context is None else str(id(context))


def db_latency_ms() -> float | None:
    """Time a ``SELECT 1`` round-trip; ``None`` on failure (no creds leak)."""
    try:
        from sqlalchemy import text

        from database import engine

        start = time.perf_counter()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return round((time.perf_counter() - start) * 1000, 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Readiness (TA6-1): DB reachable AND schema at the declared alembic head.
# ---------------------------------------------------------------------------

_heads_cache: list[str] | None = None


def alembic_heads() -> list[str]:
    """Declared migration heads, read once from ``backend/alembic/versions``.

    File-only (no DB touch, no env.py execution) and cached; [] on failure
    so readiness degrades safely instead of raising.
    """
    global _heads_cache
    if _heads_cache is None:
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            cfg = Config()
            cfg.set_main_option(
                "script_location", str(Path(__file__).resolve().parent / "alembic")
            )
            _heads_cache = list(ScriptDirectory.from_config(cfg).get_heads())
        except Exception:
            _heads_cache = []
    return _heads_cache


def applied_revisions() -> list[str]:
    """``alembic_version`` rows; empty list when missing, unreachable or broken."""
    try:
        from sqlalchemy import text

        from database import engine

        with engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars()
            return sorted(rows)
    except Exception:
        return []


def readiness_report() -> dict:
    """Safe-to-serve readiness payload: booleans, latencies, revision ids only."""
    latency = db_latency_ms()
    db_ok = latency is not None
    heads = alembic_heads()
    applied = applied_revisions() if db_ok else []
    schema_ok = db_ok and len(heads) == 1 and applied == heads
    return {
        "status": "ok" if (db_ok and schema_ok) else "not_ready",
        "db": db_ok,
        "db_latency_ms": latency,
        "schema_current": schema_ok,
        "alembic_heads": heads,
        "alembic_applied": applied,
    }


def register_healthz(app) -> None:
    """Mount ``GET /healthz`` (liveness) and ``GET /readyz`` (deployment gate).

    ``/healthz`` keeps its T3-B03 shape plus the additive ``errors_5xx``
    field; ``/readyz`` answers 200/503 per :func:`readiness_report`.
    """

    @app.get("/healthz")
    async def healthz():
        return {
            "status": "ok",
            "db_latency_ms": db_latency_ms(),
            "errors_5xx": error_5xx_count(),
        }

    @app.get("/readyz")
    async def readyz():
        report = readiness_report()
        code = 200 if report["status"] == "ok" else 503
        return JSONResponse(content=report, status_code=code)
