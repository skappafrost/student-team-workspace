"""Message CRUD with WebSocket broadcast."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import _get_channel_or_404, _get_message_or_404, get_current_user
from routers.channels import _is_private_channel_member
from services import log_activity
from ws import _ws_broadcast

router = APIRouter()


@router.get("/channels/{channel_id}/messages", response_model=list[schemas.MessageOut])
async def list_channel_messages(
    channel_id: str,
    q: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List messages in a channel, optionally filtered by a case-insensitive
    content substring (`q`). Requires workspace membership and channel access."""
    channel = _get_channel_or_404(db, channel_id)
    _require_member(channel.workspace_id, current_user["id"], db)
    if not _is_private_channel_member(channel, current_user["id"], db):
        raise HTTPException(status_code=403, detail="Not allowed to view this channel")

    query = db.query(models.Message).filter(models.Message.channel_id == channel_id)
    if q and q.strip():
        query = query.filter(models.Message.content.ilike(f"%{q.strip()}%"))
    messages = (
        query.order_by(models.Message.created_at.asc())
        .options(selectinload(models.Message.author), selectinload(models.Message.reactions))
        .all()
    )
    return messages


@router.post("/channels/{channel_id}/messages", response_model=schemas.MessageOut, status_code=201)
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
    db.flush()
    log_activity(
        db,
        workspace_id=channel.workspace_id,
        actor_id=current_user["id"],
        verb="posted in",
        target_type="channel",
        target_id=channel.id,
        target_label=f"#{channel.name}",
    )
    db.commit()
    db.refresh(message)

    # Eager-load author so the outgoing MessageOut contains author_name.
    message = (
        db.query(models.Message)
        .filter(models.Message.id == message.id)
        .options(selectinload(models.Message.author), selectinload(models.Message.reactions))
        .first()
    )

    # Broadcast to channel WebSocket room.
    message_out = schemas.MessageOut.model_validate(message).model_dump(mode="json")
    await _ws_broadcast(channel_id, {"type": "new_message", "message": message_out})

    return message


@router.patch("/messages/{message_id}", response_model=schemas.MessageOut)
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


@router.post(
    "/messages/{message_id}/reactions",
    response_model=list[schemas.ReactionSummary],
)
async def toggle_reaction(
    message_id: str,
    payload: schemas.ReactionToggle,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle the current user's emoji reaction on a message.

    Adds the reaction if absent, removes it if present. Returns the updated
    reaction summary for the message and broadcasts it to the channel room.
    """
    message = _get_message_or_404(db, message_id)
    channel = _get_channel_or_404(db, message.channel_id)
    _require_member(channel.workspace_id, current_user["id"], db)
    if not _is_private_channel_member(channel, current_user["id"], db):
        raise HTTPException(status_code=403, detail="Not allowed to react in this channel")

    existing = (
        db.query(models.MessageReaction)
        .filter(
            models.MessageReaction.message_id == message_id,
            models.MessageReaction.user_id == current_user["id"],
            models.MessageReaction.emoji == payload.emoji,
        )
        .first()
    )
    if existing is not None:
        db.delete(existing)
    else:
        db.add(
            models.MessageReaction(
                message_id=message_id, user_id=current_user["id"], emoji=payload.emoji
            )
        )
    db.commit()

    message = (
        db.query(models.Message)
        .filter(models.Message.id == message_id)
        .options(selectinload(models.Message.reactions))
        .first()
    )
    summary = schemas.MessageOut.model_validate(message).reactions
    await _ws_broadcast(
        message.channel_id,
        {
            "type": "reaction_update",
            "message_id": message_id,
            "reactions": [s.model_dump() for s in summary],
        },
    )
    return summary


@router.delete("/messages/{message_id}", status_code=204)
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
