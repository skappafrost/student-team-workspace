"""Cross-cutting domain services (R03).

Single entry points used by every router instead of inline model inserts:
- notify(): create a notification for one user
- log_activity(): append to the workspace activity feed
"""

from sqlalchemy.orm import Session

import models


def notify(
    db: Session,
    user_id: str,
    type: str,
    title: str,
    content: str | None = None,
    link: str | None = None,
) -> models.Notification:
    """Create a notification for a single user."""
    notification = models.Notification(
        user_id=user_id,
        type=type,
        title=title,
        content=content,
        link=link,
    )
    db.add(notification)
    db.flush()
    return notification


def log_activity(
    db: Session,
    workspace_id: str,
    actor_id: str,
    verb: str,
    target_type: str,
    target_id: str,
    target_label: str | None = None,
) -> models.Activity:
    """Append an entry to the workspace activity feed."""
    activity = models.Activity(
        workspace_id=workspace_id,
        actor_id=actor_id,
        verb=verb,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
    )
    db.add(activity)
    db.flush()
    return activity
