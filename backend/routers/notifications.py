"""Notification CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from database import get_db
from dependencies import _get_notification_or_404, get_current_user

router = APIRouter()


@router.post("/notifications", response_model=schemas.NotificationOut, status_code=201)
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


@router.get("/notifications", response_model=list[schemas.NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List notifications for the current user."""
    query = db.query(models.Notification).filter(models.Notification.user_id == current_user["id"])
    if unread_only:
        query = query.filter(models.Notification.read.is_(False))
    notifications = query.order_by(models.Notification.created_at.desc()).all()
    return notifications


@router.get("/notifications/{notification_id}", response_model=schemas.NotificationOut)
async def get_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single notification for the current user."""
    return _get_notification_or_404(db, notification_id, current_user["id"])


@router.patch("/notifications/{notification_id}", response_model=schemas.NotificationOut)
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


@router.delete("/notifications/{notification_id}", status_code=204)
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
