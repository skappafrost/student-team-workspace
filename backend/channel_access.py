"""Channel access predicate shared by app.py and ai_assist.py.

Single source of truth for "can this user access this channel?".
Public channels are accessible to any workspace member (the caller is
responsible for checking workspace membership first). Private channels
are accessible to the creator plus users with a row in `channel_members`.
"""

from sqlalchemy.orm import Session

import models


def is_private_channel_member(db: Session, channel: models.Channel, user_id: str) -> bool:
    """Return True if the user may access ``channel``.

    Public channels: True (workspace membership is enforced by callers).
    Private channels: the creator, or a user present in ``channel_members``.
    """
    if not channel.is_private:
        return True
    if channel.created_by == user_id:
        return True
    membership = db.query(models.ChannelMember).filter(
        models.ChannelMember.channel_id == channel.id,
        models.ChannelMember.user_id == user_id,
    ).first()
    return membership is not None


def private_channel_ids_for_user(db: Session, user_id: str) -> set[str]:
    """Return the set of channel ids the user is an explicit member of."""
    rows = (
        db.query(models.ChannelMember.channel_id)
        .filter(models.ChannelMember.user_id == user_id)
        .all()
    )
    return {row[0] for row in rows}
