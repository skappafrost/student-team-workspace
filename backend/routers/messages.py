"""Message CRUD with WebSocket broadcast."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import _get_channel_or_404, _get_message_or_404, get_current_user
from routers.channels import _is_private_channel_member
from ws import _ws_broadcast

router = APIRouter()


@router.get("/channels/{channel_id}/messages", response_model=list[schemas.MessageOut])
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
