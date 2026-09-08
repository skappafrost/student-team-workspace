"""Shared dependencies: auth tokens, current-user, cookies, resource getters."""

import os
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request, Response
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

import models

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
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        # Insecure default for local development only.
        secret = "super-secret-change-me-in-production"
    return secret


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def get_password_hash(password: str) -> str:
    # bcrypt only hashes the first 72 bytes; enforce a sane max length.
    return bcrypt.hashpw(password[:72].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


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


def _decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def get_current_user(request: Request) -> dict:
    """Return the currently authenticated user from JWT session cookie.

    Falls back to the legacy X-Test-User-* headers for existing tests.
    """
    from authorization import Role

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

    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # In a real system we would hit the DB; for speed we embed the minimal
    # identity and re-read from the database on /auth/me.
    return {"id": user_id, "name": "", "email": "", "role": Role.MEMBER.value}


def _ws_user_from_token(token: str) -> dict:
    from authorization import Role

    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return {"id": user_id, "name": "", "email": "", "role": Role.MEMBER.value}


# ---------------------------------------------------------------------------
# Session cookie helpers
# ---------------------------------------------------------------------------


def _set_session_cookie(response: Response, token: str) -> None:
    secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
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
    raw = os.getenv("CORS_ORIGINS", "")
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]


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
