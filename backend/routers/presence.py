"""Workspace presence (Task LVT S5): status set/list + realtime fan-out.

Presence is per ``(workspace, user)`` (model: ``models.PresenceState``). Status
is set two ways — an explicit ``POST /workspaces/{id}/presence/me`` (a user
choosing away/dnd/message) and the presence socket lifecycle. ``POST`` rather
than ``PUT`` because ``rate_limit._WRITE_METHODS`` excludes PUT and
``test_rate_limit.py``'s audit demands limiter coverage for every mutating
route; this app has no PUT routes at all.

One row is shared by every socket a user holds, so the socket only writes on a
transition of the live-socket count: the user's *first* connect in a workspace
goes ``online``, their *last* disconnect goes ``offline``, and extra tabs change
nothing (otherwise opening a second tab would clobber a deliberate ``dnd``).
Reads derive an idle *online* row down to *away*, and a socketless *online* row
all the way to *offline*, from the naive-UTC ``last_seen`` — so a hard crash,
which skips the disconnect handler entirely, still expires. No scheduler, no
TTL column, no sweeper: both transitions are computed at read/broadcast time.

Realtime fan-out reuses the in-process ``ws`` room manager on a dedicated
``workspace:<id>`` room (every member socket of one workspace), so a status
change reaches members on any surface they have open. The handshake reuses
``dependencies._ws_resolve_user`` and the documented 4401/4403/4404 close codes.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import _get_workspace_or_404, _utcnow, _ws_resolve_user, get_current_user
from ws import (
    WS_FORBIDDEN,
    WS_NOT_FOUND,
    _ws_broadcast_workspace,
    _ws_room_join,
    _ws_room_key_workspace,
    _ws_room_leave,
)

router = APIRouter()

PRESENCE_STATUSES = frozenset({"online", "away", "dnd", "offline"})

#: An ``online`` row whose ``last_seen`` is older than this reads as ``away``
#: (the idle→away TTL). Module-level so tests can shorten it deterministically.
AWAY_AFTER_SECONDS = 300.0

#: An ``online`` row older than this reads as ``offline`` — the safety net for a
#: hard crash, which never reaches the disconnect handler. Independent of
#: ``AWAY_AFTER_SECONDS`` so the idle→away test keeps its single knob, and only
#: *stored* ``online`` decays: a chosen ``away``/``dnd`` never does.
OFFLINE_AFTER_SECONDS = 1800.0

#: Live presence sockets per ``(workspace_id, user_id)``. Process-local, exactly
#: like ``ws._ws_rooms`` — correct on the single uvicorn worker this deployment
#: runs, and a horizontal scale needs a shared store rather than this dict.
_presence_sockets: dict[tuple[str, str], set] = {}


class PresenceIn(BaseModel):
    status: str = Field(..., min_length=1)
    status_message: str | None = Field(None, max_length=255)


def _naive(dt):
    """Normalize a stored timestamp to naive UTC for cross-dialect comparison."""
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo else dt


def effective_status(row: models.PresenceState | None, now=None) -> str:
    """Display status: no row → offline; idle online → away; stale online → offline."""
    if row is None:
        return "offline"
    if row.status == "online":
        idle = ((now or _utcnow()) - _naive(row.last_seen)).total_seconds()
        if idle > OFFLINE_AFTER_SECONDS:
            return "offline"
        if idle > AWAY_AFTER_SECONDS:
            return "away"
    return row.status


def get_presence(db: Session, user_id: str, workspace_id: str):
    return (
        db.query(models.PresenceState)
        .filter_by(user_id=user_id, workspace_id=workspace_id)
        .one_or_none()
    )


def set_presence(
    db: Session,
    *,
    user_id: str,
    workspace_id: str,
    status: str,
    status_message: str | None = None,
    commit: bool = True,
) -> models.PresenceState:
    """Upsert a member's presence row; refresh ``last_seen`` to now."""
    if status not in PRESENCE_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid presence status: {status}")
    row = get_presence(db, user_id, workspace_id)
    if row is None:
        row = models.PresenceState(user_id=user_id, workspace_id=workspace_id)
        db.add(row)
    row.status = status
    row.status_message = status_message
    row.last_seen = _utcnow()
    if commit:
        db.commit()
    return row


def _row_out(row: models.PresenceState | None, user_id: str, name: str | None = None) -> dict:
    return {
        "user_id": user_id,
        "name": name,
        "status": effective_status(row),
        "status_message": row.status_message if row else None,
        "last_seen": _naive(row.last_seen).isoformat() if row and row.last_seen else None,
    }


def _require_member_role(db: Session, workspace_id: str, user_id: str):
    """Membership + guest gate: presence is a member feature (mirrors channels)."""
    membership = _require_member(workspace_id, user_id, db)
    role = membership.role if membership.role in [r.value for r in Role] else Role.GUEST.value
    if ROLE_HIERARCHY[Role(role)] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot use presence")
    return membership


@router.get("/workspaces/{workspace_id}/presence")
async def list_presence(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Every member's effective presence in the workspace (members only)."""
    ws = _get_workspace_or_404(db, workspace_id)
    _require_member_role(db, ws.id, current_user["id"])
    members = (
        db.query(models.User, models.WorkspaceMembership)
        .join(models.WorkspaceMembership, models.WorkspaceMembership.user_id == models.User.id)
        .filter(models.WorkspaceMembership.workspace_id == ws.id)
        .all()
    )
    rows = {
        r.user_id: r
        for r in db.query(models.PresenceState).filter_by(workspace_id=ws.id).all()
    }
    return [_row_out(rows.get(user.id), user.id, user.display_name) for user, _ in members]


@router.post("/workspaces/{workspace_id}/presence/me")
async def set_my_presence(
    workspace_id: str,
    payload: PresenceIn,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set the caller's own presence and fan the change out to the workspace."""
    ws = _get_workspace_or_404(db, workspace_id)
    _require_member_role(db, ws.id, current_user["id"])
    row = set_presence(
        db,
        user_id=current_user["id"],
        workspace_id=ws.id,
        status=payload.status,
        status_message=payload.status_message,
    )
    user = db.get(models.User, current_user["id"])
    db.commit()
    out = _row_out(row, current_user["id"], user.display_name if user else None)
    await _publish(ws.id, out)
    return out


async def _publish(workspace_id: str, out: dict) -> None:
    await _ws_broadcast_workspace(
        workspace_id, {"type": "presence_update", "workspace_id": workspace_id, **out}
    )


async def _set_and_publish(workspace_id: str, user_id: str, status: str, message=None) -> None:
    """Persist a presence transition and fan it out (used by the socket)."""
    db = next(get_db())
    try:
        row = set_presence(
            db, user_id=user_id, workspace_id=workspace_id, status=status, status_message=message
        )
        user = db.get(models.User, user_id)
        out = _row_out(row, user_id, user.display_name if user else None)
    finally:
        db.close()
    await _publish(workspace_id, out)


def _presence_join(workspace_id: str, user_id: str, websocket) -> bool:
    """Track a socket; True when it is the user's first in this workspace.

    No ``await`` in here or in :func:`_presence_leave`: the 0→1 / 1→0 decision
    has to be atomic within one event-loop tick, or two concurrent handshakes
    could each conclude they were first.
    """
    key = (workspace_id, user_id)
    sockets = _presence_sockets.get(key)
    if sockets is None:
        sockets = _presence_sockets[key] = set()
    sockets.add(websocket)
    return len(sockets) == 1


def _presence_leave(workspace_id: str, user_id: str, websocket) -> bool:
    """Stop tracking a socket; True when the user now holds none.

    Idempotent, and the key is dropped once empty so the dict cannot keep an
    entry per historical member.
    """
    key = (workspace_id, user_id)
    sockets = _presence_sockets.get(key)
    if sockets is None:
        return False
    sockets.discard(websocket)
    if sockets:
        return False
    del _presence_sockets[key]
    return True


@router.websocket("/ws/workspaces/{workspace_id}/presence")
async def presence_websocket(websocket: WebSocket, workspace_id: str):
    """Presence socket: first connect→online, frame→set status, last bye→offline.

    Rejection happens before ``accept()`` so the client sees a documented 4xxx
    close code, matching the channel socket's contract.
    """
    db = next(get_db())
    try:
        user, close_code, close_reason, subproto = _ws_resolve_user(websocket, db)
        if user is None:
            await websocket.close(code=close_code, reason=close_reason or "")
            return
        try:
            ws = _get_workspace_or_404(db, workspace_id)
            _require_member_role(db, ws.id, user["id"])
        except HTTPException as exc:
            code = WS_NOT_FOUND if exc.status_code == 404 else WS_FORBIDDEN
            await websocket.close(code=code, reason=exc.detail or "Forbidden")
            return
    finally:
        db.close()

    await websocket.accept(subprotocol=subproto)
    key = _ws_room_key_workspace(workspace_id)
    _ws_room_join(key, websocket)
    try:
        if _presence_join(workspace_id, user["id"], websocket):
            await _set_and_publish(workspace_id, user["id"], "online")
        while True:
            raw = await websocket.receive_text()
            status, message = "online", None
            if raw.strip().startswith("{"):
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                if frame.get("type") == "presence":
                    status = frame.get("status", "online")
                    message = frame.get("status_message")
            if status in PRESENCE_STATUSES:
                await _set_and_publish(workspace_id, user["id"], status, message)
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _ws_room_leave(key, websocket)
        if _presence_leave(workspace_id, user["id"], websocket):
            await _set_and_publish(workspace_id, user["id"], "offline")
