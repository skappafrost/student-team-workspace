"""FastAPI application with workspace CRUD and invite endpoints."""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
import os
import uuid

from fastapi import Depends, FastAPI, File as FileParam, HTTPException, Path, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

import mimetypes
from pathlib import Path

import bcrypt

from database import Base, SessionLocal, engine, get_db
from email_sender import send_invite_email
import models
import schemas
import ai_assist


# ---------------------------------------------------------------------------
# Auth configuration
# ---------------------------------------------------------------------------

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week
REFRESH_TOKEN_EXPIRE_DAYS = 7


def _utcnow() -> datetime:
    """Naive UTC timestamp.

    Naive on purpose: SQLite's DateTime(timezone=True) round-trips values
    without tzinfo, so every stored/compared timestamp stays consistent.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        # Insecure default for local development only.
        secret = "super-secret-change-me-in-production"
    return secret


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def get_password_hash(password: str) -> str:
    # bcrypt only hashes the first 72 bytes; enforce a sane max length.
    return bcrypt.hashpw(password[:72].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


ROLE_HIERARCHY = {
    Role.OWNER: 4,
    Role.ADMIN: 3,
    Role.MEMBER: 2,
    Role.GUEST: 1,
}


# ---------------------------------------------------------------------------
# Auth dependency (JWT via httpOnly cookie)
# ---------------------------------------------------------------------------

class AuthUser(BaseModel):
    id: str
    name: str
    email: str
    role: str


def _token_from_request(request: Request) -> Optional[str]:
    # Production path: session_token httpOnly cookie set by /auth/login.
    token = request.cookies.get("session_token")
    if token:
        return token
    # Test/legacy path: Authorization: Bearer *** header.
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1]
    return None


def _token_from_cookies(cookies: dict[str, str]) -> Optional[str]:
    return cookies.get("session_token")


def _token_from_query(query: dict[str, str]) -> Optional[str]:
    return query.get("session_token") or None


def _decode_token(token: str) -> Optional[dict]:
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
    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return {"id": user_id, "name": "", "email": "", "role": Role.MEMBER.value}


# In-memory room manager for WebSocket connections.
# Maps channel_id -> set of active WebSocket connections.
_ws_rooms: dict[str, set] = {}


def _ws_room_join(channel_id: str, websocket) -> None:
    _ws_rooms.setdefault(channel_id, set()).add(websocket)


def _ws_room_leave(channel_id: str, websocket) -> None:
    room = _ws_rooms.get(channel_id)
    if room:
        room.discard(websocket)
        if not room:
            _ws_rooms.pop(channel_id, None)


async def _ws_broadcast(channel_id: str, payload: dict) -> None:
    import json
    room = _ws_rooms.get(channel_id)
    if not room:
        return
    message = json.dumps(payload)
    dead = []
    for ws in list(room):
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        room.discard(ws)
        _ws_room_leave(channel_id, ws)


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUser


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Student Team Workspace API")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _file_type(mime_type: Optional[str]) -> str:
    if not mime_type:
        return "other"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type in ("application/pdf",) or mime_type.startswith("text/") or "document" in mime_type:
        return "document"
    return "other"


def _file_out(file: models.File, request: Request = None) -> dict:
    return {
        "id": file.id,
        "workspace_id": file.workspace_id,
        "project_id": file.project_id,
        "task_id": file.task_id,
        "message_id": file.message_id,
        "name": file.original_name,
        "type": _file_type(file.mime_type),
        "size": file.size_bytes,
        "url": f"/uploads/{file.storage_key}",
        "uploaded_by": file.uploader_id,
        "created_at": file.created_at,
    }


# Create tables on startup for simplicity in this scaffold stage.
@app.on_event("startup")
def _create_tables():
    Base.metadata.create_all(bind=engine)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/channels/{channel_id}")
async def channel_websocket(websocket: WebSocket, channel_id: str):
    await websocket.accept()

    # Authenticate using cookie or query param.
    token = _token_from_cookies(websocket.cookies) or _token_from_query(websocket.query_params)
    if not token:
        await websocket.close(code=1008, reason="Missing session_token")
        return

    try:
        user = _ws_user_from_token(token)
    except HTTPException:
        await websocket.close(code=1008, reason="Invalid session_token")
        return

    # Validate channel membership.
    db = next(get_db())
    try:
        channel = _get_channel_or_404(db, channel_id)
        membership = _require_member(channel.workspace_id, user["id"], db)
        user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
        if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
            await websocket.close(code=1008, reason="Guests cannot join channel")
            return
        if not _is_private_channel_member(channel, user["id"], db):
            await websocket.close(code=1008, reason="Not allowed to join this channel")
            return
    finally:
        db.close()
    _ws_room_join(channel_id, websocket)
    try:
        while True:
            # Keep connection open; clients can send heartbeats if desired.
            data = await websocket.receive_text()
            # Echo back a heartbeat acknowledgement.
            await websocket.send_json({"type": "pong", "channel_id": channel_id})
    except WebSocketDisconnect:
        pass
    finally:
        _ws_room_leave(channel_id, websocket)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.post("/auth/register", response_model=TokenOut, status_code=201)
async def register(payload: RegisterIn, response: Response, db: Session = Depends(get_db)):
    """Register a new user and return an JWT session."""
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = models.User(
        email=payload.email,
        display_name=payload.email.split("@")[0],
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    _set_session_cookie(response, access_token)

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=AuthUser(id=user.id, name=user.display_name, email=user.email, role=Role.MEMBER.value),
    )


@app.post("/auth/login", response_model=TokenOut)
async def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    """Authenticate a user and return a JWT session."""
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    _set_session_cookie(response, access_token)

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=AuthUser(id=user.id, name=user.display_name, email=user.email, role=Role.MEMBER.value),
    )


@app.get("/auth/me", response_model=AuthUser)
async def me(request: Request, db: Session = Depends(get_db)):
    """Return the current authenticated user."""
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return AuthUser(id=user.id, name=user.display_name, email=user.email, role=Role.MEMBER.value)


@app.post("/auth/logout")
async def logout(response: Response):
    """Clear the session cookie."""
    _clear_session_cookie(response)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Workspace CRUD
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_min_role(current_user: dict, required_role: Role) -> None:
    user_role_value = current_user.get("role", Role.GUEST.value)
    try:
        user_role = Role(user_role_value)
    except ValueError:
        user_role = Role.GUEST
    user_level = ROLE_HIERARCHY[user_role]
    required_level = ROLE_HIERARCHY[required_role]
    if user_level < required_level:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user_role.value}' is insufficient. Requires '{required_role.value}'."
        )


# ---------------------------------------------------------------------------
# RBAC Dependencies
# ---------------------------------------------------------------------------

def require_role(required_role: Role):
    """Dependency factory that requires a minimum role globally (from token)."""
    def _check_role(
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        _require_min_role(current_user, required_role)
        return current_user
    return _check_role


def require_permission(permission: str):
    """Dependency factory that requires a specific permission."""
    # Map permissions to required roles
    PERMISSION_ROLES = {
        # Workspace permissions
        "workspace.create": Role.MEMBER,
        "workspace.delete": Role.OWNER,
        "workspace.transfer_ownership": Role.OWNER,
        "workspace.update": Role.ADMIN,
        "workspace.invite": Role.ADMIN,
        "workspace.manage_members": Role.ADMIN,
        # Member permissions
        "member.remove": Role.ADMIN,
        "member.update_role": Role.ADMIN,
        # Project permissions
        "project.create": Role.MEMBER,
        "project.update": Role.ADMIN,
        "project.delete": Role.ADMIN,
        "project.manage_members": Role.ADMIN,
    }
    
    required_role = PERMISSION_ROLES.get(permission, Role.OWNER)
    return require_role(required_role)


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
# Workspace CRUD
# ---------------------------------------------------------------------------

@app.post("/workspaces", response_model=schemas.WorkspaceDetailOut, status_code=201)
async def create_workspace(
    payload: schemas.WorkspaceCreate,
    current_user: dict = Depends(require_permission("workspace.create")),
    db: Session = Depends(get_db),
):
    """Create a new workspace and set the creator as owner."""
    # RBAC enforced by require_permission dependency
    if db.query(models.Workspace).filter(models.Workspace.slug == payload.slug).first():
        raise HTTPException(status_code=409, detail="Workspace slug already exists")

    workspace = models.Workspace(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
    )
    db.add(workspace)
    db.flush()  # get workspace.id

    membership = models.WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=current_user["id"],
        role=Role.OWNER.value,
    )
    db.add(membership)
    db.commit()
    db.refresh(workspace)
    db.refresh(membership)
    workspace.memberships = [membership]
    return workspace


@app.get("/workspaces", response_model=list[schemas.WorkspaceOut])
async def list_workspaces(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List workspaces the current user is a member of."""
    memberships = db.query(models.WorkspaceMembership).filter(
        models.WorkspaceMembership.user_id == current_user["id"]
    ).all()
    workspace_ids = [m.workspace_id for m in memberships]
    if not workspace_ids:
        return []
    workspaces = db.query(models.Workspace).filter(models.Workspace.id.in_(workspace_ids)).all()
    return workspaces


def _get_workspace_or_404(db: Session, workspace_id: str) -> models.Workspace:
    workspace = db.query(models.Workspace).options(
        selectinload(models.Workspace.members)
    ).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@app.get("/workspaces/{workspace_id}", response_model=schemas.WorkspaceDetailOut)
async def get_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single workspace if the current user is a member."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    return workspace


@app.patch("/workspaces/{workspace_id}", response_model=schemas.WorkspaceDetailOut)
async def update_workspace(
    workspace_id: str,
    payload: schemas.WorkspaceUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a workspace. Requires admin or higher role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    # Check user has admin role in this workspace
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.ADMIN, db)

    if payload.name is not None:
        workspace.name = payload.name
    if payload.slug is not None:
        if payload.slug != workspace.slug and db.query(models.Workspace).filter(
            models.Workspace.slug == payload.slug
        ).first():
            raise HTTPException(status_code=409, detail="Workspace slug already exists")
        workspace.slug = payload.slug
    if payload.description is not None:
        workspace.description = payload.description

    db.commit()
    db.refresh(workspace)
    return workspace


@app.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a workspace. Requires owner role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.OWNER, db)
    db.delete(workspace)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@app.post("/workspaces/{workspace_id}/invites", response_model=schemas.InviteOut, status_code=201)
async def create_invite(
    workspace_id: str,
    payload: schemas.InviteCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Invite a user by email to a workspace. Requires admin or higher role."""
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.ADMIN, db)

    # Prevent duplicate active invite for same email/workspace.
    existing = db.query(models.WorkspaceInvite).filter(
        models.WorkspaceInvite.workspace_id == workspace_id,
        models.WorkspaceInvite.email == payload.email,
        models.WorkspaceInvite.accepted_at.is_(None),
        models.WorkspaceInvite.expires_at > _utcnow(),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Active invite already exists for this email")

    invite = models.WorkspaceInvite(
        workspace_id=workspace_id,
        email=payload.email,
        role=payload.role or Role.MEMBER.value,
        expires_at=_utcnow() + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    send_invite_email(
        email=invite.email,
        token=invite.token,
        workspace_name=workspace.name,
    )
    return invite


@app.post("/invites/accept", response_model=schemas.WorkspaceMembershipOut, status_code=201)
async def accept_invite(
    payload: schemas.InviteAccept,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept an invitation by token and become a workspace member."""
    invite = db.query(models.WorkspaceInvite).filter(
        models.WorkspaceInvite.token == payload.token
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Invite already accepted")
    if invite.expires_at < _utcnow():
        raise HTTPException(status_code=410, detail="Invite expired")

    # Mark accepted
    invite.accepted_at = _utcnow()

    # Create membership
    membership = models.WorkspaceMembership(
        workspace_id=invite.workspace_id,
        user_id=current_user["id"],
        role=invite.role,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


@app.get("/workspaces/{workspace_id}/invites", response_model=list[schemas.InviteOut])
async def list_workspace_invites(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all pending invitations for a workspace. Requires admin or higher role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.ADMIN, db)
    invites = db.query(models.WorkspaceInvite).filter(
        models.WorkspaceInvite.workspace_id == workspace_id,
        models.WorkspaceInvite.accepted_at.is_(None),
        models.WorkspaceInvite.expires_at > _utcnow(),
    ).all()
    return invites


@app.patch("/workspaces/{workspace_id}/invites/{invite_id}", response_model=schemas.InviteOut)
async def update_invite_role(
    workspace_id: str,
    invite_id: str,
    payload: schemas.InviteRoleUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the role of a pending invitation. Requires admin or higher role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.ADMIN, db)
    invite = db.query(models.WorkspaceInvite).filter(
        models.WorkspaceInvite.id == invite_id,
        models.WorkspaceInvite.workspace_id == workspace_id,
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Invite already accepted")

    try:
        new_role = Role(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role")

    invite.role = new_role.value
    db.commit()
    db.refresh(invite)
    return invite


@app.delete("/workspaces/{workspace_id}/invites/{invite_id}", status_code=204)
async def cancel_invite(
    workspace_id: str,
    invite_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending invitation. Requires admin or higher role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.ADMIN, db)
    invite = db.query(models.WorkspaceInvite).filter(
        models.WorkspaceInvite.id == invite_id,
        models.WorkspaceInvite.workspace_id == workspace_id,
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    db.delete(invite)
    db.commit()
    return None

@app.get("/workspaces/{workspace_id}/members", response_model=list[schemas.WorkspaceMemberOut])
async def list_workspace_members(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all members of a workspace. Requires admin or higher role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.ADMIN, db)
    members = db.query(models.WorkspaceMembership).options(
        selectinload(models.WorkspaceMembership.user)
    ).filter(
        models.WorkspaceMembership.workspace_id == workspace_id
    ).all()
    return members


@app.patch("/workspaces/{workspace_id}/members/{user_id}", response_model=schemas.WorkspaceMemberOut)
async def update_member_role(
    workspace_id: str,
    user_id: str,
    payload: schemas.MemberRoleUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a member's role. Requires admin or higher role. Cannot change owner role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.ADMIN, db)
    
    membership = db.query(models.WorkspaceMembership).filter(
        models.WorkspaceMembership.workspace_id == workspace_id,
        models.WorkspaceMembership.user_id == user_id
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")
    
    # Prevent changing owner's role
    if membership.role == Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Cannot change owner's role")
    
    # Prevent self-demotion from owner
    if membership.user_id == current_user["id"] and membership.role == Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Cannot change your own role as owner")
    
    # Validate role
    try:
        new_role = Role(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    membership.role = new_role.value
    db.commit()
    db.refresh(membership)
    return membership


@app.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(
    workspace_id: str,
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a member from the workspace. Requires admin or higher role. Cannot remove owner."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.ADMIN, db)
    
    membership = db.query(models.WorkspaceMembership).filter(
        models.WorkspaceMembership.workspace_id == workspace_id,
        models.WorkspaceMembership.user_id == user_id
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")
    
    # Prevent removing owner
    if membership.role == Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Cannot remove workspace owner")
    
    # Prevent self-removal if owner
    if membership.user_id == current_user["id"] and membership.role == Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Cannot remove yourself as owner")
    
    db.delete(membership)
    db.commit()
    return None


@app.post("/workspaces/{workspace_id}/transfer-ownership", status_code=200)
async def transfer_ownership(
    workspace_id: str,
    payload: schemas.TransferOwnershipIn,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Transfer workspace ownership to another member. Requires owner role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.OWNER, db)
    
    # Get current owner's membership
    current_membership = db.query(models.WorkspaceMembership).filter(
        models.WorkspaceMembership.workspace_id == workspace_id,
        models.WorkspaceMembership.user_id == current_user["id"]
    ).first()
    if not current_membership or current_membership.role != Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Only the current owner can transfer ownership")
    
    # Get target member
    target_membership = db.query(models.WorkspaceMembership).filter(
        models.WorkspaceMembership.workspace_id == workspace_id,
        models.WorkspaceMembership.user_id == payload.user_id
    ).first()
    if not target_membership:
        raise HTTPException(status_code=404, detail="Target member not found")
    
    # Perform transfer
    current_membership.role = Role.ADMIN.value
    target_membership.role = Role.OWNER.value
    db.commit()
    db.refresh(current_membership)
    db.refresh(target_membership)
    
    return {"message": "Ownership transferred successfully", "new_owner_id": target_membership.user_id}


# ---------------------------------------------------------------------------
# Membership helpers
# ---------------------------------------------------------------------------

def _require_member(workspace_id: str, user_id: str, db: Session) -> models.WorkspaceMembership:
    membership = db.query(models.WorkspaceMembership).filter(
        models.WorkspaceMembership.workspace_id == workspace_id,
        models.WorkspaceMembership.user_id == user_id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    return membership


def _require_min_role_in_workspace(
    workspace_id: str, user_id: str, required_role: Role, db: Session
) -> models.WorkspaceMembership:
    membership = _require_member(workspace_id, user_id, db)
    user_role_value = membership.role
    try:
        user_role = Role(user_role_value)
    except ValueError:
        user_role = Role.GUEST
    user_level = ROLE_HIERARCHY[user_role]
    required_level = ROLE_HIERARCHY[required_role]
    if user_level < required_level:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user_role.value}' is insufficient. Requires '{required_role.value}'."
        )
    return membership


# ---------------------------------------------------------------------------
# Channel / Message CRUD
# ---------------------------------------------------------------------------

def _get_channel_or_404(db: Session, channel_id: str) -> models.Channel:
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


def _channel_to_dict(channel: models.Channel) -> dict:
    return {
        "id": channel.id,
        "workspace_id": channel.workspace_id,
        "name": channel.name,
        "topic": channel.topic,
        "type": channel.type if hasattr(channel, "type") else "general",
        "created_by": channel.created_by if hasattr(channel, "created_by") else None,
        "is_private": channel.is_private,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }


def _get_message_or_404(db: Session, message_id: str) -> models.Message:
    message = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def _is_private_channel_member(channel: models.Channel, user_id: str, db: Session) -> bool:
    if not channel.is_private:
        return True
    membership = db.query(models.WorkspaceMember).filter(
        models.WorkspaceMember.workspace_id == channel.workspace_id,
        models.WorkspaceMember.user_id == user_id,
    ).first()
    return membership is not None


@app.post("/workspaces/{workspace_id}/channels", response_model=schemas.ChannelOut, status_code=201)
async def create_channel(
    workspace_id: str,
    payload: schemas.ChannelCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new channel in a workspace. Requires member role or higher."""
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    # Guests cannot create channels
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot create channels")

    # Private channels require admin or higher
    is_private = payload.type == "private"
    if is_private and ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(status_code=403, detail="Only admins can create private channels")

    channel = models.Channel(
        workspace_id=workspace_id,
        name=payload.name,
        type=payload.type,
        created_by=current_user["id"],
        is_private=is_private,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


@app.get("/workspaces/{workspace_id}/channels", response_model=list[schemas.ChannelOut])
async def list_workspace_channels(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all channels in a workspace. Members see all channels; non-members are blocked."""
    _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    channels = db.query(models.Channel).filter(models.Channel.workspace_id == workspace_id).all()
    return channels


@app.get("/channels/{channel_id}/messages", response_model=list[schemas.MessageOut])
async def list_channel_messages(
    channel_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List messages in a channel. Requires workspace membership and private channel access."""
    channel = _get_channel_or_404(db, channel_id)
    _require_member(channel.workspace_id, current_user["id"], db)
    if not _is_private_channel_member(channel, current_user["id"], db):
        raise HTTPException(status_code=403, detail="Not allowed to view this channel")

    messages = (
        db.query(models.Message)
        .filter(models.Message.channel_id == channel_id)
        .order_by(models.Message.created_at.asc())
        .options(selectinload(models.Message.author))
        .all()
    )
    return messages


@app.post("/channels/{channel_id}/messages", response_model=schemas.MessageOut, status_code=201)
async def create_message(
    channel_id: str,
    payload: schemas.MessageCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new message in a channel. Requires member role or higher."""
    channel = _get_channel_or_404(db, channel_id)
    membership = _require_member(channel.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot post messages")

    if not _is_private_channel_member(channel, current_user["id"], db):
        raise HTTPException(status_code=403, detail="Not allowed to post in this channel")

    if payload.parent_id:
        parent = _get_message_or_404(db, payload.parent_id)
        if parent.channel_id != channel_id:
            raise HTTPException(status_code=400, detail="Parent message is in another channel")

    message = models.Message(
        channel_id=channel_id,
        author_id=current_user["id"],
        content=payload.content,
        parent_id=payload.parent_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    # Eager-load author so the outgoing MessageOut contains author_name.
    message = (
        db.query(models.Message)
        .filter(models.Message.id == message.id)
        .options(selectinload(models.Message.author))
        .first()
    )

    # Broadcast to channel WebSocket room.
    message_out = schemas.MessageOut.model_validate(message).model_dump(mode="json")
    await _ws_broadcast(channel_id, {"type": "new_message", "message": message_out})

    return message


@app.patch("/messages/{message_id}", response_model=schemas.MessageOut)
async def update_message(
    message_id: str,
    payload: schemas.MessageUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a message. Owner or admin/owner can edit."""
    message = _get_message_or_404(db, message_id)
    channel = _get_channel_or_404(db, message.channel_id)
    membership = _require_member(channel.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    is_admin_plus = ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]
    is_owner = message.author_id == current_user["id"]

    if not (is_owner or is_admin_plus):
        raise HTTPException(status_code=403, detail="Not allowed to update this message")

    if payload.content is not None:
        message.content = payload.content

    db.commit()
    db.refresh(message)

    # Eager-load author so the response contains author_name.
    message = (
        db.query(models.Message)
        .filter(models.Message.id == message.id)
        .options(selectinload(models.Message.author))
        .first()
    )

    return message


@app.delete("/messages/{message_id}", status_code=204)
async def delete_message(
    message_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a message. Owner or admin/owner can delete."""
    message = _get_message_or_404(db, message_id)
    channel = _get_channel_or_404(db, message.channel_id)
    membership = _require_member(channel.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    is_admin_plus = ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]
    is_owner = message.author_id == current_user["id"]

    if not (is_owner or is_admin_plus):
        raise HTTPException(status_code=403, detail="Not allowed to delete this message")

    db.delete(message)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Project and Task CRUD
# ---------------------------------------------------------------------------

def _get_event_or_404(db: Session, event_id: str) -> models.Event:
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _can_modify_event(event: models.Event, membership: models.WorkspaceMembership, current_user: dict) -> bool:
    if event.created_by == current_user["id"]:
        return True
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    return ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]


@app.post("/workspaces/{workspace_id}/events", response_model=schemas.EventOut, status_code=201)
async def create_event(
    workspace_id: str,
    payload: schemas.EventCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new event in a workspace. Any member can create."""
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot create events")

    if payload.project_id:
        project = _get_project_or_404(db, payload.project_id)
        if project.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Project not found in workspace")

    event = models.Event(
        workspace_id=workspace_id,
        project_id=payload.project_id,
        created_by=current_user["id"],
        title=payload.title,
        description=payload.description,
        start_at=payload.start_at,
        end_at=payload.end_at,
        all_day=payload.all_day,
        event_type=payload.event_type,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@app.get("/workspaces/{workspace_id}/events", response_model=list[schemas.EventOut])
async def list_workspace_events(
    workspace_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List events in a workspace, optionally filtered by start/end date range."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view events")

    query = db.query(models.Event).filter(models.Event.workspace_id == workspace_id)
    if start:
        try:
            start_dt = datetime.fromisoformat(start)
            query = query.filter(
                or_(
                    models.Event.end_at.is_(None),
                    models.Event.end_at >= start_dt,
                )
            )
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid start date format")
    if end:
        try:
            end_dt = datetime.fromisoformat(end)
            query = query.filter(models.Event.start_at <= end_dt)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid end date format")

    events = query.order_by(models.Event.start_at.asc()).all()
    return events


@app.get("/events/{event_id}", response_model=schemas.EventOut)
async def get_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single event. Must be a workspace member."""
    event = _get_event_or_404(db, event_id)
    membership = _require_member(event.workspace_id, current_user["id"], db)
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view events")
    return event


@app.patch("/events/{event_id}", response_model=schemas.EventOut)
async def update_event(
    event_id: str,
    payload: schemas.EventUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an event. Requires creator/admin/owner."""
    event = _get_event_or_404(db, event_id)
    membership = _require_member(event.workspace_id, current_user["id"], db)

    if not _can_modify_event(event, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to update this event")

    if payload.title is not None:
        event.title = payload.title
    if payload.description is not None:
        event.description = payload.description
    if payload.start_at is not None:
        event.start_at = payload.start_at
    if payload.end_at is not None:
        event.end_at = payload.end_at
    if payload.all_day is not None:
        event.all_day = payload.all_day
    if payload.event_type is not None:
        event.event_type = payload.event_type
    if payload.project_id is not None:
        if payload.project_id:
            project = _get_project_or_404(db, payload.project_id)
            if project.workspace_id != event.workspace_id:
                raise HTTPException(status_code=404, detail="Project not found in workspace")
        event.project_id = payload.project_id

    db.commit()
    db.refresh(event)
    return event


@app.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an event. Requires creator/admin/owner."""
    event = _get_event_or_404(db, event_id)
    membership = _require_member(event.workspace_id, current_user["id"], db)

    if not _can_modify_event(event, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to delete this event")

    db.delete(event)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Project and Task CRUD
# ---------------------------------------------------------------------------

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


def _require_project_access(project: models.Project, user_id: str, db: Session) -> None:
    _require_member(project.workspace_id, user_id, db)


# Projects

@app.post("/workspaces/{workspace_id}/projects", response_model=schemas.ProjectOut, status_code=201)
async def create_project(
    workspace_id: str,
    payload: schemas.ProjectCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new project inside a workspace. Any member can create."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_min_role_in_workspace(workspace_id, current_user["id"], Role.MEMBER, db)
    project = models.Project(
        workspace_id=workspace_id,
        owner_id=current_user["id"],
        name=payload.name,
        description=payload.description,
        status="active",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/workspaces/{workspace_id}/projects", response_model=list[schemas.ProjectOut])
async def list_workspace_projects(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all projects in a workspace."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    projects = db.query(models.Project).filter(models.Project.workspace_id == workspace_id).all()
    return projects


@app.get("/projects/{project_id}", response_model=schemas.ProjectOut)
async def get_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single project. Must be a workspace member."""
    project = _get_project_or_404(db, project_id)
    _require_member(project.workspace_id, current_user["id"], db)
    return project


@app.patch("/projects/{project_id}", response_model=schemas.ProjectOut)
async def update_project(
    project_id: str,
    payload: schemas.ProjectUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a project. Requires owner/admin or project creator."""
    project = _get_project_or_404(db, project_id)
    membership = _require_member(project.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    is_admin_plus = ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]
    is_creator = project.owner_id == current_user["id"]

    if not (is_admin_plus or is_creator):
        raise HTTPException(status_code=403, detail="Not allowed to update this project")

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.status is not None:
        project.status = payload.status

    db.commit()
    db.refresh(project)
    return project


@app.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a project. Requires owner/admin."""
    project = _get_project_or_404(db, project_id)
    membership = _require_member(project.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(status_code=403, detail="Not allowed to delete this project")

    db.delete(project)
    db.commit()
    return None


# Tasks

@app.post("/projects/{project_id}/tasks", response_model=schemas.TaskOut, status_code=201)
async def create_task(
    project_id: str,
    payload: schemas.TaskCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new task inside a project. Any workspace member can create."""
    project = _get_project_or_404(db, project_id)
    _require_member(project.workspace_id, current_user["id"], db)

    task = models.Task(
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        assignee_id=payload.assignee_id,
        priority=payload.priority,
        status=payload.status,
        position=payload.position,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.get("/projects/{project_id}/tasks", response_model=list[schemas.TaskOut])
async def list_project_tasks(
    project_id: str,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tasks in a project, optionally filtered by status."""
    project = _get_project_or_404(db, project_id)
    _require_member(project.workspace_id, current_user["id"], db)

    query = db.query(models.Task).filter(models.Task.project_id == project_id)
    if status:
        query = query.filter(models.Task.status == status)
    tasks = query.order_by(models.Task.position.asc(), models.Task.created_at.asc()).all()
    return tasks


@app.patch("/tasks/{task_id}", response_model=schemas.TaskOut)
async def update_task(
    task_id: str,
    payload: schemas.TaskUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a task (incl. status/column move + assignee). Any workspace member can update."""
    task = _get_task_or_404(db, task_id)
    project = _get_project_or_404(db, task.project_id)
    _require_member(project.workspace_id, current_user["id"], db)

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.assignee_id is not None:
        task.assignee_id = payload.assignee_id
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.status is not None:
        task.status = payload.status
    if payload.position is not None:
        task.position = payload.position

    db.commit()
    db.refresh(task)
    return task


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a task. Requires owner/admin or task creator."""
    task = _get_task_or_404(db, task_id)
    project = _get_project_or_404(db, task.project_id)
    membership = _require_member(project.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    is_admin_plus = ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]
    is_creator = task.assignee_id == current_user["id"] or task.project.owner_id == current_user["id"]

    if not (is_admin_plus or is_creator):
        raise HTTPException(status_code=403, detail="Not allowed to delete this task")

    db.delete(task)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Page (Knowledge Base) CRUD
# ---------------------------------------------------------------------------

def _get_page_or_404(db: Session, page_id: str) -> models.Page:
    page = db.query(models.Page).filter(models.Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


def _validate_parent_id(db: Session, workspace_id: str, parent_id: str, page_id: Optional[str] = None) -> None:
    parent = _get_page_or_404(db, parent_id)
    if parent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Parent page not found in workspace")
    if page_id is not None and parent.id == page_id:
        raise HTTPException(status_code=400, detail="Page cannot be its own parent")


def _check_page_write_permission(page: models.Page, membership: models.WorkspaceMembership, current_user: dict) -> bool:
    user_role_value = membership.role
    user_role = Role(user_role_value) if user_role_value in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]:
        return True
    return page.created_by == current_user["id"]


@app.post("/workspaces/{workspace_id}/pages", response_model=schemas.PageOut, status_code=201)
async def create_page(
    workspace_id: str,
    payload: schemas.PageCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new page in a workspace. Requires member role or higher."""
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot create pages")

    if payload.parent_id:
        _validate_parent_id(db, workspace_id, payload.parent_id)

    # Slug uniqueness within workspace
    existing = db.query(models.Page).filter(
        models.Page.workspace_id == workspace_id,
        models.Page.slug == payload.slug,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Page slug already exists in this workspace")

    page = models.Page(
        workspace_id=workspace_id,
        parent_id=payload.parent_id,
        title=payload.title,
        slug=payload.slug,
        content=payload.content,
        created_by=current_user["id"],
        updated_by=current_user["id"],
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


@app.get("/workspaces/{workspace_id}/pages", response_model=list[schemas.PageTreeItem])
async def list_workspace_pages(
    workspace_id: str,
    flat: bool = False,
    search: str | None = None,
    recent: bool = False,
    limit: int = Query(default=10, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List pages in a workspace as a tree or flat list.

    Query params:
      - search: filter title/content by ILIKE (case-insensitive, flat list only).
      - recent: order by updated_at desc and return up to ``limit`` pages (flat).
      - limit: maximum number of recent/search results to return (default 10, max 100).
    """
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view pages")

    query = db.query(models.Page).filter(models.Page.workspace_id == workspace_id)

    if search is not None:
        term = search.strip()
        if not term:
            return []
        like_term = f"%{term}%"
        query = query.filter(
            or_(models.Page.title.ilike(like_term), models.Page.content.ilike(like_term))
        ).order_by(models.Page.updated_at.desc())
        return query.all()

    if recent:
        return query.order_by(models.Page.updated_at.desc()).limit(limit).all()

    pages = query.order_by(models.Page.created_at.asc()).all()

    if flat:
        return pages

    # Build tree: only root pages with nested children loaded lazily; build recursively
    root_pages = [p for p in pages if p.parent_id is None]
    return root_pages


@app.get("/workspaces/{workspace_id}/pages/{page_id}", response_model=schemas.PageOut)
async def get_page(
    workspace_id: str,
    page_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single page. Must be a workspace member."""
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view pages")

    page = _get_page_or_404(db, page_id)
    if page.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Page not found in workspace")
    return page


@app.patch("/workspaces/{workspace_id}/pages/{page_id}", response_model=schemas.PageOut)
async def update_page(
    workspace_id: str,
    page_id: str,
    payload: schemas.PageUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a page. Requires creator or admin/owner."""
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    page = _get_page_or_404(db, page_id)
    if page.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Page not found in workspace")

    if not _check_page_write_permission(page, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to update this page")

    if payload.parent_id is not None:
        if payload.parent_id:
            _validate_parent_id(db, workspace_id, payload.parent_id, page_id=page.id)
        page.parent_id = payload.parent_id

    if payload.title is not None:
        page.title = payload.title
    if payload.slug is not None:
        # Slug uniqueness within workspace
        existing = db.query(models.Page).filter(
            models.Page.workspace_id == workspace_id,
            models.Page.slug == payload.slug,
        ).first()
        if existing and existing.id != page.id:
            raise HTTPException(status_code=409, detail="Page slug already exists in this workspace")
        page.slug = payload.slug
    if payload.content is not None:
        page.content = payload.content

    page.updated_by = current_user["id"]
    db.commit()
    db.refresh(page)
    return page


@app.delete("/workspaces/{workspace_id}/pages/{page_id}", status_code=204)
async def delete_page(
    workspace_id: str,
    page_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a page. Requires admin/owner."""
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    page = _get_page_or_404(db, page_id)
    if page.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Page not found in workspace")

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(status_code=403, detail="Only admins can delete pages")

    db.delete(page)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# AI Assist endpoints
# ---------------------------------------------------------------------------

class SummarizeRequest(BaseModel):
    kind: str
    ref_id: str


class SummarizeResponse(BaseModel):
    summary: str


class SearchResponse(BaseModel):
    results: list[dict]


@app.post("/ai/summarize", response_model=SummarizeResponse)
async def ai_summarize(
    payload: SummarizeRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a summary for a task, page, or channel."""
    kind = payload.kind
    ref_id = payload.ref_id
    user_id = current_user["id"]

    if kind == "task":
        result = ai_assist.summarize_task(db, ref_id, user_id)
    elif kind == "page":
        result = ai_assist.summarize_page(db, ref_id, user_id)
    elif kind == "channel":
        result = ai_assist.summarize_channel(db, ref_id, user_id)
    else:
        raise HTTPException(status_code=422, detail="Invalid kind. Must be task, page, or channel.")

    return {"summary": result["summary"]}


@app.get("/ai/search", response_model=SearchResponse)
async def ai_search(
    q: str = Query(..., min_length=1),
    scope: str = Query("tasks,pages,messages"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search across tasks, pages, and messages in workspaces the user can access."""
    scope_list = [s.strip() for s in scope.split(",") if s.strip()]
    results = ai_assist.search_workspace(db, current_user["id"], q, scope_list)

    return {
        "results": [
            {
                "kind": r.kind,
                "id": r.id,
                "title": r.title,
                "snippet": r.snippet,
                "workspace_id": r.workspace_id,
                "score": r.score,
            }
            for r in results
        ]
    }


# ---------------------------------------------------------------------------
# Notification CRUD
# ---------------------------------------------------------------------------

def _get_notification_or_404(db: Session, notification_id: str, user_id: str) -> models.Notification:
    notification = db.query(models.Notification).filter(models.Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to access this notification")
    return notification


@app.post("/notifications", response_model=schemas.NotificationOut, status_code=201)
async def create_notification(
    payload: schemas.NotificationCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a notification for a user."""
    # Verify target user exists
    target_user = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    notification = models.Notification(
        user_id=payload.user_id,
        type=payload.type,
        title=payload.title,
        content=payload.content,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


@app.get("/notifications", response_model=list[schemas.NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List notifications for the current user."""
    query = db.query(models.Notification).filter(
        models.Notification.user_id == current_user["id"]
    )
    if unread_only:
        query = query.filter(models.Notification.read == False)
    notifications = query.order_by(models.Notification.created_at.desc()).all()
    return notifications


@app.get("/notifications/{notification_id}", response_model=schemas.NotificationOut)
async def get_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single notification for the current user."""
    return _get_notification_or_404(db, notification_id, current_user["id"])


@app.patch("/notifications/{notification_id}", response_model=schemas.NotificationOut)
async def update_notification(
    notification_id: str,
    payload: schemas.NotificationUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a notification as read/unread."""
    notification = _get_notification_or_404(db, notification_id, current_user["id"])
    notification.read = payload.read
    db.commit()
    db.refresh(notification)
    return notification


@app.delete("/notifications/{notification_id}", status_code=204)
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a notification."""
    notification = _get_notification_or_404(db, notification_id, current_user["id"])
    db.delete(notification)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Static file serving for uploads
# ---------------------------------------------------------------------------
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# ---------------------------------------------------------------------------
# File CRUD helpers
# ---------------------------------------------------------------------------
def _get_file_or_404(db: Session, file_id: str) -> models.File:
    file = db.query(models.File).filter(models.File.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    return file


def _can_modify_file(file: models.File, membership: models.WorkspaceMembership, current_user: dict) -> bool:
    user_role_value = membership.role
    user_role = Role(user_role_value) if user_role_value in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]:
        return True
    return file.uploader_id == current_user["id"]


# ---------------------------------------------------------------------------
# File CRUD endpoints
# ---------------------------------------------------------------------------
@app.post("/workspaces/{workspace_id}/files", status_code=201)
async def upload_file(
    workspace_id: str,
    file: UploadFile = FileParam(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file to a workspace. Requires member role or higher."""
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot upload files")

    if not file.filename:
        raise HTTPException(status_code=422, detail="File name is required")

    content = await file.read()
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=422, detail="File is empty")

    mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    storage_key = f"{uuid.uuid4()}_{file.filename}"
    file_path = UPLOAD_DIR / storage_key
    file_path.write_bytes(content)

    db_file = models.File(
        workspace_id=workspace_id,
        uploader_id=current_user["id"],
        original_name=file.filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size,
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    # Emit a notification for the uploader about the successful upload.
    notification = models.Notification(
        user_id=current_user["id"],
        type="file-upload",
        title="File uploaded",
        content=f"Your file {file.filename} was uploaded successfully.",
    )
    db.add(notification)
    db.commit()

    return _file_out(db_file)


@app.get("/workspaces/{workspace_id}/files")
async def list_workspace_files(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List files in a workspace. Members can view."""
    workspace = _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view files")

    files = db.query(models.File).filter(models.File.workspace_id == workspace_id).order_by(
        models.File.created_at.desc()
    ).all()
    return [_file_out(f) for f in files]


@app.get("/files/{file_id}")
async def get_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single file. Must be a workspace member."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view files")

    return _file_out(file)


@app.patch("/files/{file_id}")
async def update_file(
    file_id: str,
    payload: schemas.FileUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a file's metadata. Requires creator or admin/owner."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    if not _can_modify_file(file, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to update this file")

    if payload.name is not None:
        file.original_name = payload.name

    db.commit()
    db.refresh(file)
    return _file_out(file)


@app.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a file. Requires admin/owner."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(status_code=403, detail="Only admins can delete files")

    storage_path = UPLOAD_DIR / file.storage_key
    if storage_path.exists():
        storage_path.unlink()

    db.delete(file)
    db.commit()
    return None
