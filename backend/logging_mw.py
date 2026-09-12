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
"""

import base64
import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("stw.requests")


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


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach ``X-Request-Id`` and log one safe info line per request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("X-Request-Id", "")
        request_id = _sanitize_request_id(incoming) or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "%s %s 500 %.1fms user=%s req=%s",
                request.method,
                request.url.path,
                elapsed_ms,
                request_user_id(request),
                request_id,
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %s %.1fms user=%s req=%s",
            request.method,
            request.url.path,
            status,
            elapsed_ms,
            request_user_id(request),
            request_id,
        )
        response.headers["X-Request-Id"] = request_id
        return response


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


def register_healthz(app) -> None:
    """Mount ``GET /healthz`` with a ``SELECT 1`` latency readout."""

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "db_latency_ms": db_latency_ms()}
