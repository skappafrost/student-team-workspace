"""Message CRUD with WebSocket broadcast."""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

import models
import pagination as pagination_lib
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import _get_channel_or_404, _get_message_or_404, get_current_user
from query_utils import LIKE_ESCAPE, contains_pattern
from routers.channels import _is_private_channel_member
from services import log_activity
from ws import _ws_broadcast_channel, _ws_notify_user

router = APIRouter()


def _resolve_mentions(db: Session, workspace_id: str, content: str) -> list[str]:
    """Resolve @mention tokens in message content to workspace member ids.

    Conservative by design (TA4-1): a token only matches when the text after
    ``@`` is the FULL display name of exactly one workspace member (matching
    is case-insensitive; names that collide modulo case are skipped as
    ambiguous). Substring or prefix matches are ignored, and users who are
    not members of the workspace are never notified.
    """
    if "@" not in content:
        return []
    members = (
        db.query(models.WorkspaceMember)
        .filter(models.WorkspaceMember.workspace_id == workspace_id)
        .all()
    )
    if not members:
        return []
    # Map case-folded full display names to user ids. A name claimed by two
    # different members becomes None (ambiguous) and is never resolved.
    by_name: dict[str, str | None] = {}
    for membership in members:
        user = membership.user
        if user is None or not user.display_name:
            continue
        name = user.display_name.strip()
        if not name:
            continue
        key = name.casefold()
        if key in by_name and by_name[key] != membership.user_id:
            by_name[key] = None
        else:
            by_name[key] = membership.user_id
    resolved: list[str] = []
    # Longest names are matched first so "@Alice Bob" prefers the full name
    # over the prefix "Alice".
    for key in sorted(by_name, key=len, reverse=True):
        user_id = by_name[key]
        if user_id is None:
            continue
        # The name must not be followed by another word character, so a
        # mention of "@AliceBlueprint" never resolves to "Alice".
        pattern = re.compile(rf"@{re.escape(key)}(?![\w])", re.IGNORECASE)
        match = pattern.search(content)
        if match:
            resolved.append(user_id)
            # Mask the matched span so a shorter name that is a prefix of
            # this one ("Alice" inside "@Alice Bob") cannot match it again.
            content = (
                content[: match.start()]
                + " " * (match.end() - match.start())
                + content[match.end() :]
            )
    return resolved


def _notify_message_fanout(
    db: Session,
    *,
    channel: models.Channel,
    message: models.Message,
    author_id: str,
) -> None:
    """Create notifications for a freshly created message (TA4-1).

    Fan-out rules:
    - DM channels: notify the peer (the channel member who is not the author).
    - @mentions: notify members whose full display name appears as a token.
    - Thread replies: notify the parent message's author.
    Dedupe: each user is notified at most once per message, and the author
    never notifies themselves. Notification types reuse the existing
    ``NotificationType`` vocabulary: "dm", "mention", "thread".
    """
    recipients: dict[str, str] = {}  # user_id -> notification type

    if channel.type == "dm":
        members = (
            db.query(models.ChannelMember)
            .filter(models.ChannelMember.channel_id == channel.id)
            .all()
        )
        for member_row in members:
            if member_row.user_id != author_id:
                recipients[member_row.user_id] = "dm"

    for user_id in _resolve_mentions(db, channel.workspace_id, message.content):
        recipients.setdefault(user_id, "mention")

    if message.parent_id is not None:  # thread reply
        parent = db.get(models.Message, message.parent_id)
        if parent is not None and parent.author_id != author_id:
            recipients.setdefault(parent.author_id, "thread")

    recipients.pop(author_id, None)

    author = db.get(models.User, author_id)
    author_name = author.display_name if author else "Someone"
    link = f"/dashboard/chat?channel={channel.id}"
    for user_id, note_type in recipients.items():
        if note_type == "dm":
            title = f"New message from {author_name}"
            content = f"{author_name} sent you a direct message."
        elif note_type == "thread":
            title = f"New reply from {author_name}"
            content = f"{author_name} replied to your message."
        else:
            title = f"{author_name} mentioned you"
            content = f"{author_name} mentioned you in #{channel.name}."
        notify(
            db,
            user_id=user_id,
            type=note_type,
            title=title,
            content=content,
            link=link,
        )


@router.get("/channels/{channel_id}/messages", response_model=list[schemas.MessageOut])
async def list_channel_messages(
    channel_id: str,
    q: str | None = None,
    limit: int | None = pagination_lib.limit_query(
        "Maximum number of messages to return (default = the 1000 cap)."
    ),
    offset: int | None = pagination_lib.offset_query(),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List messages in a channel, optionally filtered by a case-insensitive
    content substring (`q`). Requires workspace membership and channel access.

    Pagination: ``limit`` (1..1000; default = the 1000 cap, i.e. the whole
    collection), ``offset`` (default 0).
    """
    channel = _get_channel_or_404(db, channel_id)
    _require_member(channel.workspace_id, current_user["id"], db)
    if not _is_private_channel_member(channel, current_user["id"], db):
        raise HTTPException(status_code=403, detail="Not allowed to view this channel")

    query = db.query(models.Message).filter(models.Message.channel_id == channel_id)
    if q and q.strip():
        query = query.filter(models.Message.content.ilike(f"%{q.strip()}%"))
    _limit, _offset = pagination_lib.parse_list_params(limit, offset)
    messages = (
        query.order_by(models.Message.created_at.asc())
        .options(selectinload(models.Message.author), selectinload(models.Message.reactions))
        .offset(_offset)
        .limit(_limit)
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
    _notify_message_fanout(
        db, channel=channel, message=message, author_id=current_user["id"]
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
    await _ws_broadcast_channel(channel_id, {"type": "new_message", "message": message_out})

    # Fan out notifications to any open socket owned by each recipient
    # (TA4-2). The notification row is created by the caller (fan-out PR)
    # or the notify() service; here we only push the already-serialized
    # shape so a client can merge it without an extra request.
    await _ws_notify_recipients(db, channel, message, current_user["id"])

    return message


async def _ws_notify_recipients(db, channel, message, author_id: str) -> None:
    """Push ``notification_created`` to the sockets of users who care.

    Mirrors the message-fan-out rules (DM peer, thread parent author) so a
    user with an open tab learns about a new message immediately even when
    they are not viewing that channel. Non-members are never notified and
    the author never notifies themselves.
    """
    recipients: list[str] = []
    if channel.type == "dm":
        peer = (
            db.query(models.ChannelMember.user_id)
            .filter(
                models.ChannelMember.channel_id == channel.id,
                models.ChannelMember.user_id != author_id,
            )
            .first()
        )
        if peer:
            recipients.append(peer[0])
    elif message.parent_id:
        parent = db.get(models.Message, message.parent_id)
        if parent and parent.author_id != author_id:
            recipients.append(parent.author_id)

    for user_id in recipients:
        notification = (
            db.query(models.Notification)
            .filter(
                models.Notification.user_id == user_id,
                models.Notification.type == "message",
                models.Notification.content.like(f"%{message.id}%"),
            )
            .first()
        )
        if notification is None:
            continue
        await _ws_notify_user(
            user_id,
            schemas.NotificationOut.model_validate(notification).model_dump(mode="json"),
        )


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
    await _ws_broadcast_channel(
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
