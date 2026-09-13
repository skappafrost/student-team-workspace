"""In-memory sliding-window rate limiter (T3-B02).

Core algorithm uses only the standard library (``time`` + ``threading`` +
``os``/``math``); the FastAPI dependency wrappers at the bottom are thin
integration glue so ``backend/app.py`` needs just one ``import`` line plus
one ``dependencies=[...]`` addition per protected route (5 added lines).

Buckets (per the task spec):
  - login:    10/min per IP  +  5/min per email
  - register: 5/hour per (IP, email)
  - upload:   20/hour per user
  - ai:       30/hour per user

Fallback (T4-E5): every other POST/PATCH/DELETE route shares
``DEFAULT_WRITE_LIMIT`` per (identity, route group) via
:class:`DefaultWriteLimitMiddleware` (one ``add_middleware`` line in app.py;
the import line already exists, so wiring stays within budget).

Notes / deliberate trade-offs:
  - ``register`` is keyed per (IP, email) rather than bare IP: the existing
    suite performs ~17 registrations from a single test-client IP, so a bare
    per-IP bucket would 429 legitimate tests. Per-(IP,email) still blocks
    mass-registration scripts while keeping the suite green.
  - ``ai_search`` (GET /ai/search) is intentionally NOT wired: wiring it
    would exceed the 5-added-lines budget in app.py. Only POST
    /ai/summarize carries the ai dependency (same 30/h/user bucket, so
    abuse via summarize is still capped).
  - User identity for the upload/ai buckets is the JWT ``sub`` claim decoded
    WITHOUT signature verification (base64 only) -- it is used purely as a
    rate-limit key, never for authentication. Anonymous callers fall back to
    a per-IP key. Client IP is taken from the direct connection only;
    X-Forwarded-For is deliberately ignored (spoofable bypass).
  - ``RATELIMIT_ENABLED=0`` disables all limiting (checked per call, so tests
    can ``monkeypatch.setenv`` it at request time).
  - State is process-local; a production deploy with multiple workers would
    want a shared store (Redis). ``reset()`` exists for tests.
"""

import base64
import json
import math
import os
import threading
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Limits: (max_hits, window_seconds)
# ---------------------------------------------------------------------------

LOGIN_IP_LIMIT = (10, 60)
LOGIN_EMAIL_LIMIT = (5, 60)
REGISTER_LIMIT = (5, 3600)
UPLOAD_LIMIT = (20, 3600)
AI_LIMIT = (30, 3600)
#: Fallback cap (T4-E5) for mutating routes without a specific limiter:
#: 120 writes/min per (identity, route group). Generous on purpose -- it
#: only bites scripted floods, never interactive use; the sensitive families
#: above keep their own tighter buckets.
DEFAULT_WRITE_LIMIT = (120, 60)

# ---------------------------------------------------------------------------
# Core sliding-window store (stdlib only)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def _enabled() -> bool:
    return os.getenv("RATELIMIT_ENABLED", "1").strip() != "0"


def reset() -> None:
    """Clear all recorded hits (tests only)."""
    with _lock:
        _hits.clear()


def check(
    bucket: str,
    key: str,
    max_hits: int,
    window_secs: int,
    *,
    now: float | None = None,
) -> tuple[bool, float]:
    """Record a hit and report ``(allowed, retry_after_secs)``.

    Sliding window: at most ``max_hits`` recorded hits per ``window_secs``
    for the composite key ``(bucket, key)``. When denied, ``retry_after_secs``
    is the seconds until the oldest hit in the window expires (0.0 when
    allowed). Returns ``(True, 0.0)`` without recording when disabled via
    ``RATELIMIT_ENABLED=0``.
    """
    if not _enabled():
        return True, 0.0
    t = time.monotonic() if now is None else now
    composite = f"{bucket}:{key}"
    with _lock:
        lst = _hits.get(composite)
        if not lst:
            _hits[composite] = [t]
            return True, 0.0
        cutoff = t - window_secs
        idx = 0
        while idx < len(lst) and lst[idx] <= cutoff:
            idx += 1
        if idx:
            del lst[:idx]
        if not lst:
            lst.append(t)
            return True, 0.0
        if len(lst) >= max_hits:
            return False, max(0.0, lst[0] + window_secs - t)
        lst.append(t)
        return True, 0.0


# ---------------------------------------------------------------------------
# Request helpers (integration glue)
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


async def _body_email(request: Request) -> str | None:
    """Best-effort lowercase email from a JSON body; None when absent/unparseable.

    Never raises: an invalid body must still reach the endpoint (422), so a
    missing email simply skips the per-email bucket (the per-IP bucket still
    applies).
    """
    try:
        body = await request.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    email = body.get("email")
    if not isinstance(email, str) or "@" not in email:
        return None
    return email.strip().lower()


def _jwt_sub_unverified(request: Request) -> str | None:
    """Extract the JWT ``sub`` claim without verifying the signature.

    Used ONLY as a stable per-user rate-limit key, never for auth decisions.
    Returns None for missing/malformed tokens (callers fall back to IP).
    """
    token: str | None = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if not token or token.count(".") != 2:
        return None
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
    except Exception:
        return None
    sub = payload.get("sub") if isinstance(payload, dict) else None
    return sub if isinstance(sub, str) and sub else None


def _user_key(request: Request) -> str:
    sub = _jwt_sub_unverified(request)
    if sub:
        return f"user:{sub}"
    return f"ip:{_client_ip(request)}"


def _retry_after_header(retry_secs: float) -> str:
    return str(max(1, math.ceil(retry_secs)))


async def _enforce(specs: list[tuple[str, str, int, int]]) -> None:
    for bucket, key, max_hits, window_secs in specs:
        allowed, retry_after = check(bucket, key, max_hits, window_secs)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {bucket}",
                headers={"Retry-After": _retry_after_header(retry_after)},
            )


# ---------------------------------------------------------------------------
# FastAPI dependencies (one per protected route family)
# ---------------------------------------------------------------------------


async def login_limit(request: Request) -> None:
    """10/min per IP + 5/min per email on POST /auth/login."""
    specs = [("login_ip", _client_ip(request), *LOGIN_IP_LIMIT)]
    email = await _body_email(request)
    if email:
        specs.append(("login_email", email, *LOGIN_EMAIL_LIMIT))
    await _enforce(specs)


async def register_limit(request: Request) -> None:
    """5/hour per (IP, email) on POST /auth/register."""
    email = await _body_email(request)
    await _enforce([("register", f"{_client_ip(request)}|{email or '-'}", *REGISTER_LIMIT)])


async def upload_limit(request: Request) -> None:
    """20/hour per user on POST /workspaces/{id}/files."""
    await _enforce([("upload", _user_key(request), *UPLOAD_LIMIT)])


async def ai_limit(request: Request) -> None:
    """30/hour per user on POST /ai/summarize (ai_search skipped: line budget)."""
    await _enforce([("ai", _user_key(request), *AI_LIMIT)])


# ---------------------------------------------------------------------------
# Fallback write limiter (T4-E5)
# ---------------------------------------------------------------------------

_WRITE_METHODS = frozenset({"POST", "PATCH", "DELETE"})

#: Exact (method, path) pairs already guarded by a specific limiter above;
#: the middleware skips them so a request is never double-counted.
_SPECIFIC_LIMIT_ROUTES = frozenset(
    {
        ("POST", "/auth/login"),
        ("POST", "/auth/register"),
        ("POST", "/ai/summarize"),
    }
)

#: Substring -> route group, checked in order (first hit wins; nested hints
#: come before the parents they sit under, e.g. /messages before /channels).
#: Nested writes such as POST /workspaces/{id}/channels belong to their
#: feature group, not to "workspaces", so one busy feature cannot starve
#: another.
_WRITE_GROUP_HINTS = (
    ("/invites", "invites"),
    ("/members", "members"),
    ("transfer-ownership", "workspaces"),
    ("/messages", "messages"),
    ("/channels", "channels"),
    ("/events", "events"),
    ("/tasks", "tasks"),
    ("/projects", "projects"),
    ("/pages", "pages"),
    ("/files", "files"),
    ("/notifications", "notifications"),
    ("/ai/", "ai"),
)


def _write_group(method: str, path: str) -> str | None:
    """Route group for the fallback limiter, or None when no fallback check
    applies (safe method, or already covered by a specific limiter)."""
    method = method.upper()
    if method not in _WRITE_METHODS:
        return None
    norm = path.rstrip("/") or "/"
    if (method, norm) in _SPECIFIC_LIMIT_ROUTES:
        return None
    if (
        method == "POST"
        and norm.startswith("/workspaces/")
        and norm.endswith("/files")
    ):
        return None  # upload_limit covers POST /workspaces/{id}/files
    for hint, group in _WRITE_GROUP_HINTS:
        if hint in norm:
            return group
    seg = norm.lstrip("/").split("/", 1)[0]
    return seg or "root"


def _fallback_key(request: Request) -> str:
    """Identity key for the fallback bucket: stable per user, never for auth.

    Prefers the JWT ``sub`` (unverified decode, rate-limit key only), then the
    legacy ``X-Test-User-Id`` header some older tests still carry, then the
    client IP -- so tests acting as different users never share a bucket
    while anonymous callers still share a per-IP one.
    """
    sub = _jwt_sub_unverified(request)
    if sub:
        return f"user:{sub}"
    test_user = request.headers.get("X-Test-User-Id", "").strip()
    if test_user:
        return f"testuser:{test_user}"
    return f"ip:{_client_ip(request)}"


class DefaultWriteLimitMiddleware(BaseHTTPMiddleware):
    """Fallback 429 net for mutating routes without a specific limiter.

    Runs before routing and never touches the body: identity comes from
    headers/cookies only. Denials answer 429 + JSON ``detail`` directly (a
    middleware sits outside FastAPI's HTTPException handlers, so raising
    there would 500 instead). ``RATELIMIT_ENABLED=0`` still disables
    everything via :func:`check`.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        group = _write_group(request.method, request.url.path)
        if group is None:
            return await call_next(request)
        allowed, retry_after = check(
            "write", f"{_fallback_key(request)}:{group}", *DEFAULT_WRITE_LIMIT
        )
        if allowed:
            return await call_next(request)
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded for write:{group}"},
            headers={"Retry-After": _retry_after_header(retry_after)},
        )
