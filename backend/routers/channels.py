"""Channel CRUD + channel WebSocket endpoint."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session, selectinload

import channel_access
import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import (
    _get_channel_or_404,
    _get_workspace_or_404,
    _ws_resolve_user,
    get_current_user,
)
from ws import (
    WS_FORBIDDEN,
    WS_NOT_FOUND,
    WS_SUBPROTOCOL,
    _ws_broadcast_channel,
    _ws_room_join,
    _ws_room_key_channel,
    _ws_room_key_user,
    _ws_room_leave,
)

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
    """Public channels: any workspace member. Private: creator or channel_members row.

    Mirrors channel_access.is_private_channel_member (kept as the single source
    of truth for ai_assist); duplicated here with this module's arg order.
    """
    if not channel.is_private:
        return True
    if channel.created_by == user_id:
        return True
    return (
        db.query(models.ChannelMember)
        .filter(
            models.ChannelMember.channel_id == channel.id,
            models.ChannelMember.user_id == user_id,
        )
        .first()
        is not None
    )


def _require_channel_manager(
    channel: models.Channel, current_user: dict, db: Session
) -> models.WorkspaceMember:
    """Admins/owners or the channel creator may manage a channel."""
    membership = _require_member(channel.workspace_id, current_user["id"], db)
    if channel.created_by == current_user["id"]:
        return membership
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(
            status_code=403,
            detail="Only admins or the channel creator can manage this channel",
        )
    return membership


def _channel_member_out(cm: models.ChannelMember) -> dict:
    return {
        "channel_id": cm.channel_id,
        "user_id": cm.user_id,
        "display_name": cm.user.display_name if cm.user else None,
        "email": cm.user.email if cm.user else None,
        "joined_at": cm.joined_at.isoformat() if cm.joined_at else None,
    }


def _dm_out(channel: models.Channel, user_id: str, db: Session) -> schemas.DMChannelOut:
    return _dm_out_with_peer(channel, _dm_peers(db, [channel], user_id).get(channel.id))


def _dm_out_with_peer(
    channel: models.Channel, peer: models.User | None
) -> schemas.DMChannelOut:
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


def _dm_peers(db: Session, channels: list[models.Channel], user_id: str) -> dict[str, models.User]:
    """Batched peer lookup: one query for every channel instead of one per row.

    Returns {channel_id: peer User} — the first non-``user_id`` member of each
    channel, matching what the per-row ``.first()`` query produced (DM channels
    hold exactly two members by construction).
    """
    if not channels:
        return {}
    rows = (
        db.query(models.ChannelMember.channel_id, models.User)
        .join(models.User, models.User.id == models.ChannelMember.user_id)
        .filter(
            models.ChannelMember.channel_id.in_([c.id for c in channels]),
            models.ChannelMember.user_id != user_id,
        )
        .all()
    )
    peers: dict[str, models.User] = {}
    for channel_id, peer in rows:
        peers.setdefault(channel_id, peer)
    return peers


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
    if candidates:
        # One batched query for every candidate's members (was 1 per channel).
        member_rows = (
            db.query(models.ChannelMember.channel_id, models.ChannelMember.user_id)
            .filter(models.ChannelMember.channel_id.in_([c.id for c in candidates]))
            .all()
        )
        members_by_channel: dict[str, set[str]] = {}
        for channel_id, member_user_id in member_rows:
            members_by_channel.setdefault(channel_id, set()).add(member_user_id)
        for channel in candidates:
            if members_by_channel.get(channel.id, set()) == set(pair):
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
    peers = _dm_peers(db, channels, current_user["id"])
    return [_dm_out_with_peer(c, peers.get(c.id)) for c in channels]


@router.websocket("/ws/channels/{channel_id}")
async def channel_websocket(websocket: WebSocket, channel_id: str):
    """Authenticated channel socket: chat frames in, broadcast frames out.

    Handshake order matters: every rejection happens BEFORE ``accept()`` so
    the client observes a refused upgrade with a documented 4xxx code
    (see docs/API.md) instead of a session that opens and instantly dies.

    Auth precedence: negotiated ``stw-ws.<ticket>`` subprotocol (one-shot
    ticket from ``POST /auth/ws-ticket``, never in a URL) > ``session_token``
    cookie (browser default) > ``?session_token=`` query (test/legacy).
    """
    user, close_code, close_reason, subproto = _ws_resolve_user(websocket)
    if user is None:
        await websocket.close(code=close_code, reason=close_reason or "")
        return

    # Validate channel + membership BEFORE joining any room.
    db = next(get_db())
    try:
        try:
            channel = _get_channel_or_404(db, channel_id)
        except HTTPException as exc:
            # 404 -> not found; anything else (impossible here) -> forbidden.
            await websocket.close(
                code=WS_NOT_FOUND if exc.status_code == 404 else WS_FORBIDDEN,
                reason="Channel not found",
            )
            return
        membership = _require_member(channel.workspace_id, user["id"], db)
        user_role = (
            Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
        )
        if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
            await websocket.close(code=WS_FORBIDDEN, reason="Guests cannot join channel")
            return
        if not _is_private_channel_member(channel, user["id"], db):
            await websocket.close(code=WS_FORBIDDEN, reason="Not allowed to join this channel")
            return
        db_user = db.get(models.User, user["id"])
        user_name = db_user.display_name if db_user else "Someone"
    finally:
        db.close()

    await websocket.accept(subprotocol=subproto or WS_SUBPROTOCOL)

    chan_key = _ws_room_key_channel(channel_id)
    user_key = _ws_room_key_user(user["id"])
    _ws_room_join(chan_key, websocket)
    _ws_room_join(user_key, websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            # Client frames: plain heartbeat text or JSON {"type": "typing"}.
            if raw.strip().startswith("{"):
                import json as _json

                try:
                    frame = _json.loads(raw)
                except ValueError:
                    continue
                if frame.get("type") == "typing":
                    await _ws_broadcast_channel(
                        channel_id,
                        {
                            "type": "typing",
                            "channel_id": channel_id,
                            "user_id": user["id"],
                            "user_name": user_name,
                        },
                        exclude=websocket,
                    )
                continue
            # Echo back a heartbeat acknowledgement.
            await websocket.send_json({"type": "pong", "channel_id": channel_id})
    except WebSocketDisconnect:
        pass
    finally:
        # Both rooms: leaving one without the other would strand the socket
        # in the user room (leaked delivery slot) or the channel room
        # (phantom broadcast target).
        _ws_room_leave(chan_key, websocket)
        _ws_room_leave(user_key, websocket)


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
    db.flush()
    if is_private:
        # Creator is always a member of their private channel.
        db.add(models.ChannelMember(channel_id=channel.id, user_id=current_user["id"]))
    db.commit()
    db.refresh(channel)
    return channel


@router.get("/workspaces/{workspace_id}/channels", response_model=list[schemas.ChannelOut])
async def list_workspace_channels(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List channels in a workspace.

    DM channels are never listed here (they live under /dms). Admins/owners
    see every other channel; regular members see public channels plus private
    channels they created or hold a channel_members row for.
    """
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    is_admin_plus = ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]

    channels = (
        db.query(models.Channel)
        .filter(
            models.Channel.workspace_id == workspace_id,
            models.Channel.type != "dm",
        )
        .all()
    )
    if not is_admin_plus:
        member_channel_ids = channel_access.private_channel_ids_for_user(db, current_user["id"])
        channels = [
            c
            for c in channels
            if not c.is_private
            or c.created_by == current_user["id"]
            or c.id in member_channel_ids
        ]
    return channels


@router.patch("/channels/{channel_id}", response_model=schemas.ChannelOut)
async def update_channel(
    channel_id: str,
    payload: schemas.ChannelUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update channel name/topic/type. Admin or creator only."""
    channel = _get_channel_or_404(db, channel_id)
    membership = _require_channel_manager(channel, current_user, db)

    if payload.type is not None and payload.type == "private":
        user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
        if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
            raise HTTPException(status_code=403, detail="Only admins can create private channels")

    if payload.name is not None:
        channel.name = payload.name
    if payload.topic is not None:
        channel.topic = payload.topic
    if payload.type is not None:
        channel.type = payload.type
        channel.is_private = payload.type == "private"
        if channel.is_private:
            # Make sure the creator stays a member when a channel becomes private.
            existing = (
                db.query(models.ChannelMember)
                .filter(
                    models.ChannelMember.channel_id == channel.id,
                    models.ChannelMember.user_id == channel.created_by,
                )
                .first()
            )
            if not existing:
                db.add(models.ChannelMember(channel_id=channel.id, user_id=channel.created_by))

    db.commit()
    db.refresh(channel)
    return channel


@router.get("/channels/{channel_id}/members", response_model=list[schemas.ChannelMemberOut])
async def list_channel_members(
    channel_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the members of a channel.

    Private channels: users with an explicit membership row. Public channels:
    all workspace members (membership is implicit).
    """
    channel = _get_channel_or_404(db, channel_id)
    _require_member(channel.workspace_id, current_user["id"], db)
    if not _is_private_channel_member(channel, current_user["id"], db):
        raise HTTPException(status_code=403, detail="Not allowed to view this channel")

    if not channel.is_private:
        rows = (
            db.query(models.WorkspaceMember)
            .filter(models.WorkspaceMember.workspace_id == channel.workspace_id)
            .options(selectinload(models.WorkspaceMember.user))
            .order_by(models.WorkspaceMember.joined_at.asc())
            .all()
        )
        return [
            {
                "channel_id": channel.id,
                "user_id": wm.user_id,
                "display_name": wm.user.display_name if wm.user else None,
                "email": wm.user.email if wm.user else None,
                "joined_at": wm.joined_at.isoformat() if wm.joined_at else None,
            }
            for wm in rows
        ]

    rows = (
        db.query(models.ChannelMember)
        .filter(models.ChannelMember.channel_id == channel_id)
        .options(selectinload(models.ChannelMember.user))
        .order_by(models.ChannelMember.joined_at.asc())
        .all()
    )
    return [_channel_member_out(cm) for cm in rows]


@router.post(
    "/channels/{channel_id}/members", response_model=schemas.ChannelMemberOut, status_code=201
)
async def add_channel_member(
    channel_id: str,
    payload: schemas.ChannelMemberAdd,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a workspace member to a private channel. Admin or creator only."""
    channel = _get_channel_or_404(db, channel_id)
    _require_channel_manager(channel, current_user, db)

    if not channel.is_private:
        raise HTTPException(
            status_code=400,
            detail="Public channels have implicit membership for all workspace members",
        )

    target = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    _require_member(channel.workspace_id, payload.user_id, db)

    existing = (
        db.query(models.ChannelMember)
        .filter(
            models.ChannelMember.channel_id == channel.id,
            models.ChannelMember.user_id == payload.user_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member of this channel")

    cm = models.ChannelMember(channel_id=channel.id, user_id=payload.user_id)
    db.add(cm)
    db.commit()
    db.refresh(cm)
    cm.user = target
    return _channel_member_out(cm)


@router.delete("/channels/{channel_id}/members/{user_id}", status_code=204)
async def remove_channel_member(
    channel_id: str,
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a user from a private channel. Admin or creator only."""
    channel = _get_channel_or_404(db, channel_id)
    _require_channel_manager(channel, current_user, db)

    if not channel.is_private:
        raise HTTPException(
            status_code=400,
            detail="Public channels have implicit membership for all workspace members",
        )

    cm = (
        db.query(models.ChannelMember)
        .filter(
            models.ChannelMember.channel_id == channel.id,
            models.ChannelMember.user_id == user_id,
        )
        .first()
    )
    if not cm:
        raise HTTPException(status_code=404, detail="User is not a member of this channel")

    db.delete(cm)
    db.commit()
    return None
