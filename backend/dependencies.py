"""Shared dependencies: auth tokens, current-user, cookies, resource getters."""

import logging
import os
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

import models
from config import settings
from ws import (
    WS_SUBPROTOCOL,
    WS_UNAUTHENTICATED,
    _ws_parse_ticket,
)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week
REFRESH_TOKEN_EXPIRE_DAYS = 7


def _utcnow() -> datetime:
    """Naive UTC timestamp.

    Naive on purpose: SQLite's DateTime(timezone=True) round-trips values
    without tzinfo, so every stored/compared timestamp stays consistent.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _get_secret() -> str:
    # Insecure default for local development only; set JWT_SECRET_KEY in prod.
    return settings.jwt_secret_key


def create_access_token(
    subject: str, expires_delta: timedelta | None = None, jti: str | None = None
) -> str:
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def create_session_pair(user_id: str, db, family_id: str | None = None) -> tuple[str, str]:
    """Mint a revocable session and its access+refresh token pair (TA1-1).

    Both tokens share one ``auth_sessions`` row (same ``jti``) so that
    ``/auth/logout``, ``/auth/logout-all`` and account deletion revoke the
    refresh token together with the access token. The refresh token carries
    the same ``jti`` and ``type: refresh`` so the access-token path can never
    accept it. ``family_id`` chains rotation successors back to the original
    login session for family invalidation.
    """
    import models

    jti = str(uuid.uuid4())
    expires_at = _utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    db.add(
        models.AuthSession(user_id=user_id, jti=jti, expires_at=expires_at, family_id=family_id)
    )
    db.flush()
    return create_access_token(user_id, jti=jti), create_refresh_token(user_id, jti=jti)


def revoke_session(db, jti: str) -> None:
    import models

    session = db.query(models.AuthSession).filter(models.AuthSession.jti == jti).first()
    if session and session.revoked_at is None:
        session.revoked_at = _utcnow()
        db.flush()


def revoke_all_sessions(db, user_id: str) -> int:
    import models

    rows = (
        db.query(models.AuthSession)
        .filter(models.AuthSession.user_id == user_id, models.AuthSession.revoked_at.is_(None))
        .all()
    )
    for row in rows:
        row.revoked_at = _utcnow()
    db.flush()
    return len(rows)


def _is_jti_revoked(db, jti: str) -> bool:
    """Revocation check against auth_sessions on the REQUEST's session.

    Single DB session per request (TA1-3): the caller passes the injected
    get_db session (or the WS handshake session), so the check shares the
    request's transaction instead of opening a second connection.
    Missing row counts as revoked.
    """
    import models

    session = db.query(models.AuthSession).filter(models.AuthSession.jti == jti).first()
    return session is None or session.revoked_at is not None


def create_refresh_token(subject: str, jti: str | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def _password_bytes(password: str) -> bytes:
    """UTF-8 encode a password and enforce bcrypt's 72-byte input limit.

    bcrypt only consumes the first 72 bytes of input; anything longer is
    silently truncated by the algorithm, creating equivalence classes (two
    different passwords hashing identically) and login mismatch. Encode FIRST,
    then reject over-limit input with a clean 422 instead of truncating.
    """
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise HTTPException(status_code=422, detail="Password exceeds 72 bytes")
    return raw


def verify_password(plain: str, hashed: str) -> bool:
    # Guard before checkpw: an over-72-byte password (e.g. multibyte chars)
    # must read as invalid credentials (401), never crash (500).
    try:
        raw = _password_bytes(plain)
    except HTTPException:
        return False
    try:
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except ValueError:
        # Corrupt/malformed hash: fail closed.
        return False


def get_password_hash(password: str) -> str:
    raw = _password_bytes(password)
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


# ---------------------------------------------------------------------------
# Auth dependency (JWT via httpOnly cookie)
# ---------------------------------------------------------------------------


class AuthUser(BaseModel):
    id: str
    name: str
    email: str
    role: str


def _token_from_request(request: Request) -> str | None:
    # Production path: session_token httpOnly cookie set by /auth/login.
    token = request.cookies.get("session_token")
    if token:
        return token
    # Test/legacy path: Authorization: Bearer *** header.
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1]
    return None


def _token_from_cookies(cookies: dict[str, str]) -> str | None:
    return cookies.get("session_token")


def _token_from_query(query: dict[str, str]) -> str | None:
    return query.get("session_token") or None


# ---------------------------------------------------------------------------
# Short-lived WebSocket handshake tickets (TA4-2)
# ---------------------------------------------------------------------------
#
# A browser cannot attach headers to a WebSocket handshake, and query-string
# tokens land in access logs. The negotiated path is therefore a one-shot
# ticket minted by an authenticated REST call (``POST /auth/ws-ticket``),
# offered as the ``Sec-WebSocket-Protocol`` value ``stw-ws.<ticket>`` so it
# never appears in a URL. The cookie path stays as a fallback for the
# browser client and for tests.
#
# The store is process-local: tickets are only useful to the process that
# will serve the socket, and the TTL is short enough that a restart is not
# a support burden. A horizontal-scale deployment would swap this for a
# shared TTL store; the API below is the contract to keep.

_WS_TICKET_TTL_SECONDS = 60
_ws_ticket_store: dict[str, tuple[str, float]] = {}
_ws_ticket_lock = threading.Lock()


def _ws_ticket_is_enabled() -> bool:
    """Tickets are optional in dev/test (cookie fallback covers tests).

    Enabled by default in any deployment that is not explicitly test/dev,
    mirroring the JWT-secret governance rule: the safer mode is the default.
    """
    if os.getenv("STW_TEST_AUTH", "").strip() == "1":
        return False
    return os.getenv("ENVIRONMENT", "").strip().lower() not in {"test", "dev"}


def _ws_ticket_prune(now: float | None = None) -> None:
    """Drop expired tickets (cheap: called on mint and on read miss)."""
    cutoff = time.time() if now is None else now
    with _ws_ticket_lock:
        for key in [k for k, (_, exp) in _ws_ticket_store.items() if exp <= cutoff]:
            _ws_ticket_store.pop(key, None)


def create_ws_ticket(user_id: str) -> str | None:
    """Mint a one-shot ticket binding ``user_id`` for the next WS handshake.

    Returns None when tickets are disabled (dev/test), in which case the WS
    endpoint falls back to the session cookie.
    """
    if not user_id:
        return None
    if not _ws_ticket_is_enabled():
        return None
    _ws_ticket_prune()
    ticket = secrets.token_urlsafe(24)
    with _ws_ticket_lock:
        # One live ticket per user: a new mint replaces the old one.
        for key in [k for k, (uid, _) in _ws_ticket_store.items() if uid == user_id]:
            _ws_ticket_store.pop(key, None)
        _ws_ticket_store[ticket] = (user_id, time.time() + _WS_TICKET_TTL_SECONDS)
    return ticket


def _user_from_ws_ticket(ticket: str | None) -> str | None:
    """Consume a ticket; returns the user_id, or None if invalid/expired.

    Tickets are single-use: a replay attempt does not authenticate, and a
    consumed ticket is removed from the store either way.
    """
    if not ticket or not _ws_ticket_is_enabled():
        return None
    _ws_ticket_prune()
    with _ws_ticket_lock:
        entry = _ws_ticket_store.pop(ticket, None)
    if entry is None:
        return None
    user_id, expires_at = entry
    if time.time() >= expires_at:
        return None
    return user_id


def _decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        # Tokens minted via create_session carry a jti; revoked/unknown jti = dead.
        # Legacy jti-less tokens (tests) pass through.
        jti = payload.get("jti")
        if jti and _is_jti_revoked(db, jti):
            return None
        return payload
    except JWTError:
        return None


def _test_auth_bypass_enabled() -> bool:
    """The X-Test-User-* bypass is active only in explicit test mode.

    Reads the environment at request time (not import time) so tests can
    monkeypatch it. The bypass requires BOTH ``STW_TEST_AUTH=1`` and
    ``ENVIRONMENT`` in {"test", "dev"} (belt and suspenders, T003).
    """
    if os.getenv("STW_TEST_AUTH", "").strip() != "1":
        return False
    return os.getenv("ENVIRONMENT", "").strip() in {"test", "dev"}


_test_auth_warned = False


def _warn_test_auth_once() -> None:
    """Startup-visible warning when the bypass flag is ON (logged once per process)."""
    global _test_auth_warned
    if _test_auth_warned:
        return
    _test_auth_warned = True
    logging.getLogger("uvicorn.error").warning(
        "STW_TEST_AUTH=1: X-Test-User-* header auth bypass is ACTIVE (environment=%r). "
        "Never enable outside test/dev.",
        os.environ.get("ENVIRONMENT", ""),
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    """Return the currently authenticated user from JWT session cookie.

    Falls back to the legacy X-Test-User-* headers ONLY when the test-only
    bypass is explicitly enabled (STW_TEST_AUTH=1 + ENVIRONMENT test/dev, T003).
    The bypass is never active in normal/CI runs; the suite authenticates with
    real JWTs.

    The get_db dependency is what makes the jti revocation check share the
    request's session (TA1-3): FastAPI resolves it once per request, ahead
    of any endpoint Depends(get_db), so both see the SAME session.
    """
    from authorization import Role

    if _test_auth_bypass_enabled():
        _warn_test_auth_once()
        override = request.headers.get("X-Test-User-Id")
        if override:
            return {
                "id": override,
                "name": "Test User",
                "role": request.headers.get("X-Test-User-Role", Role.OWNER.value),
            }

    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = _decode_token(token, db)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # In a real system we would hit the DB; for speed we embed the minimal
    # identity and re-read from the database on /auth/me.
    return {"id": user_id, "name": "", "email": "", "role": Role.MEMBER.value}


def _ws_user_from_token(token: str, db) -> dict:
    from authorization import Role

    payload = _decode_token(token, db)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return {"id": user_id, "name": "", "email": "", "role": Role.MEMBER.value}


def _ws_resolve_user(websocket) -> tuple[dict | None, int | None, str | None, str | None]:
    """Resolve the WS handshake identity: ticket first, then cookie/query.

    Returns ``(user, close_code, close_reason, accepted_subprotocol)``.
    ``user is None`` means the handshake must be rejected with ``close_code``
    BEFORE ``websocket.accept()``, so the client sees a refused upgrade
    carrying a documented 4xxx code instead of a session that opens then
    immediately dies with an ambiguous 1008.
    """
    from authorization import Role

    raw_subprotocol = websocket.headers.get("sec-websocket-protocol")
    ticket = _ws_parse_ticket(raw_subprotocol)
    ticket_user_id = _user_from_ws_ticket(ticket)
    if ticket_user_id is not None:
        # Ticket path: the REST mint call already proved the JWT. The ticket
        # is single-use and now consumed; no token is decoded again here.
        return (
            {"id": ticket_user_id, "name": "", "email": "", "role": Role.MEMBER.value},
            None,
            None,
            WS_SUBPROTOCOL,
        )

    token = _token_from_cookies(websocket.cookies) or _token_from_query(
        websocket.query_params
    )
    if not token:
        return (None, WS_UNAUTHENTICATED, "Missing session_token", None)
    try:
        user = _ws_user_from_token(token)
    except HTTPException:
        return (None, WS_UNAUTHENTICATED, "Invalid session_token", None)
    return (user, None, None, None)


# ---------------------------------------------------------------------------
# Session cookie helpers
# ---------------------------------------------------------------------------


def _set_session_cookie(response: Response, token: str) -> None:
    secure = settings.cookie_secure
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key="session_token", path="/")


def _parse_cors_origins() -> list[str]:
    return settings.cors_origin_list()


# ---------------------------------------------------------------------------
# Resource getters (raise 404 when missing)
# ---------------------------------------------------------------------------


def _get_workspace_or_404(db: Session, workspace_id: str) -> models.Workspace:
    workspace = (
        db.query(models.Workspace)
        .options(selectinload(models.Workspace.members))
        .filter(models.Workspace.id == workspace_id)
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _get_channel_or_404(db: Session, channel_id: str) -> models.Channel:
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


def _get_message_or_404(db: Session, message_id: str) -> models.Message:
    message = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def _get_event_or_404(db: Session, event_id: str) -> models.Event:
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _get_project_or_404(db: Session, project_id: str) -> models.Project:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_task_or_404(db: Session, task_id: str) -> models.Task:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _get_page_or_404(db: Session, page_id: str) -> models.Page:
    page = db.query(models.Page).filter(models.Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


def _get_file_or_404(db: Session, file_id: str) -> models.File:
    file = db.query(models.File).filter(models.File.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    return file


def _get_notification_or_404(
    db: Session, notification_id: str, user_id: str
) -> models.Notification:
    notification = (
        db.query(models.Notification).filter(models.Notification.id == notification_id).first()
    )
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to access this notification")
    return notification
