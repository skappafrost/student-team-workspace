"""Channel CRUD + channel WebSocket endpoint."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import (
    _get_channel_or_404,
    _get_workspace_or_404,
    _token_from_cookies,
    _token_from_query,
    _ws_user_from_token,
    get_current_user,
)
from ws import _ws_room_join, _ws_room_leave

router = APIRouter()


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


def _is_private_channel_member(channel: models.Channel, user_id: str, db: Session) -> bool:
    if not channel.is_private:
        return True
    # Channels with explicit channel members (e.g. DMs) are restricted to them.
    has_members = (
        db.query(models.ChannelMember)
        .filter(models.ChannelMember.channel_id == channel.id)
        .first()
        is not None
    )
    if has_members:
        return (
            db.query(models.ChannelMember)
            .filter(
                models.ChannelMember.channel_id == channel.id,
                models.ChannelMember.user_id == user_id,
            )
            .first()
            is not None
        )
    membership = (
        db.query(models.WorkspaceMember)
        .filter(
            models.WorkspaceMember.workspace_id == channel.workspace_id,
            models.WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    return membership is not None


def _dm_out(channel: models.Channel, user_id: str, db: Session) -> schemas.DMChannelOut:
    peer = (
        db.query(models.User)
        .join(models.ChannelMember, models.ChannelMember.user_id == models.User.id)
        .filter(
            models.ChannelMember.channel_id == channel.id,
            models.ChannelMember.user_id != user_id,
        )
        .first()
    )
    return schemas.DMChannelOut(
        id=channel.id,
        workspace_id=channel.workspace_id,
        name=channel.name,
        type=channel.type,
        created_by=channel.created_by,
        is_private=channel.is_private,
        created_at=channel.created_at,
        peer_id=peer.id if peer else None,
        peer_name=peer.display_name if peer else None,
    )


@router.post(
    "/workspaces/{workspace_id}/dms", response_model=schemas.DMChannelOut, status_code=201
)
async def create_dm(
    workspace_id: str,
    payload: schemas.DMCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create (or return existing) 1:1 direct-message channel with another member."""
    _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    if payload.user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot open a DM with yourself")
    _require_member(workspace_id, payload.user_id, db)

    pair = sorted([current_user["id"], payload.user_id])
    # Find an existing DM channel between exactly these two users.
    candidates = (
        db.query(models.Channel)
        .filter(
            models.Channel.workspace_id == workspace_id,
            models.Channel.type == "dm",
        )
        .all()
    )
    for channel in candidates:
        member_ids = {
            m.user_id
            for m in db.query(models.ChannelMember)
            .filter(models.ChannelMember.channel_id == channel.id)
            .all()
        }
        if member_ids == set(pair):
            return _dm_out(channel, current_user["id"], db)

    channel = models.Channel(
        workspace_id=workspace_id,
        name=f"dm-{pair[0]}-{pair[1]}",
        type="dm",
        created_by=current_user["id"],
        is_private=True,
    )
    db.add(channel)
    db.flush()
    db.add_all(
        [
            models.ChannelMember(channel_id=channel.id, user_id=pair[0]),
            models.ChannelMember(channel_id=channel.id, user_id=pair[1]),
        ]
    )
    db.commit()
    db.refresh(channel)
    return _dm_out(channel, current_user["id"], db)


@router.get("/workspaces/{workspace_id}/dms", response_model=list[schemas.DMChannelOut])
async def list_dms(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the current user's DM channels in a workspace."""
    _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    channels = (
        db.query(models.Channel)
        .join(models.ChannelMember, models.ChannelMember.channel_id == models.Channel.id)
        .filter(
            models.Channel.workspace_id == workspace_id,
            models.Channel.type == "dm",
            models.ChannelMember.user_id == current_user["id"],
        )
        .all()
    )
    return [_dm_out(c, current_user["id"], db) for c in channels]


@router.websocket("/ws/channels/{channel_id}")
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
        user_role = (
            Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
        )
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
            await websocket.receive_text()
            # Echo back a heartbeat acknowledgement.
            await websocket.send_json({"type": "pong", "channel_id": channel_id})
    except WebSocketDisconnect:
        pass
    finally:
        _ws_room_leave(channel_id, websocket)


@router.post(
    "/workspaces/{workspace_id}/channels", response_model=schemas.ChannelOut, status_code=201
)
async def create_channel(
    workspace_id: str,
    payload: schemas.ChannelCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new channel in a workspace. Requires member role or higher."""
    _get_workspace_or_404(db, workspace_id)
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


@router.get("/workspaces/{workspace_id}/channels", response_model=list[schemas.ChannelOut])
async def list_workspace_channels(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all channels in a workspace. Members see all channels; non-members are blocked."""
    _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    channels = (
        db.query(models.Channel)
        .filter(
            models.Channel.workspace_id == workspace_id,
            models.Channel.type != "dm",
        )
        .all()
    )
    return channels
