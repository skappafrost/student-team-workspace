"""Account self-service: data export + deletion (S03).

Deletion policy (anonymize, don't cascade):
- The user row is anonymized (display name, email tombstone, password/avatar
  cleared, is_active=False) so shared content (messages, tasks, comments)
  keeps referential integrity under a "Deleted user" attribution.
- Private data is hard-deleted: memberships, notifications, auth sessions,
  files (row + blob on disk).
- Workspaces owned solely by the deleted user are NOT auto-deleted; ownership
  transfer is a separate explicit flow.
"""

import contextlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from config import settings
from database import get_db
from dependencies import (
    _clear_session_cookie,
    get_current_user,
    verify_password,
)

router = APIRouter()


class DeleteAccountIn(BaseModel):
    password: str


def _export_payload(db: Session, user: models.User) -> dict:
    user_id = user.id
    tasks = db.query(models.Task).filter(models.Task.assignee_id == user_id).all()
    messages = db.query(models.Message).filter(models.Message.author_id == user_id).all()
    files = db.query(models.File).filter(models.File.uploader_id == user_id).all()
    pages = db.query(models.Page).filter(models.Page.created_by == user_id).all()
    events = db.query(models.Event).filter(models.Event.created_by == user_id).all()
    comments = db.query(models.TaskComment).filter(models.TaskComment.author_id == user_id).all()
    memberships = (
        db.query(models.WorkspaceMember).filter(models.WorkspaceMember.user_id == user_id).all()
    )

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "memberships": [
            {"workspace_id": m.workspace_id, "role": m.role} for m in memberships
        ],
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status,
                "priority": t.priority,
                "due_at": t.due_at.isoformat() if t.due_at else None,
            }
            for t in tasks
        ],
        "messages": [
            {
                "id": m.id,
                "channel_id": m.channel_id,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "comments": [
            {"id": c.id, "task_id": c.task_id, "content": c.content} for c in comments
        ],
        "pages": [
            {"id": p.id, "title": p.title, "slug": p.slug, "content": p.content}
            for p in pages
        ],
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "start_at": e.start_at.isoformat() if e.start_at else None,
                "end_at": e.end_at.isoformat() if e.end_at else None,
            }
            for e in events
        ],
        "files": [
            {
                "id": f.id,
                "original_name": f.original_name,
                "mime_type": f.mime_type,
                "size_bytes": f.size_bytes,
            }
            for f in files
        ],
    }


@router.get("/users/me/export")
async def export_my_data(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download all of the current user's data as a JSON document."""
    user = db.query(models.User).filter(models.User.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    payload = _export_payload(db, user)
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="stw-export-{user.id}.json"',
        },
    )


@router.delete("/users/me")
async def delete_my_account(
    payload: DeleteAccountIn,
    response: Response,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete the account after password confirmation.

    Anonymizes the user row; purges memberships, notifications, sessions,
    and uploaded files (rows + blobs).
    """
    user = db.query(models.User).filter(models.User.id == current_user["id"]).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Invalid password")

    # Purge uploaded files (rows + blobs on disk).
    upload_dir = Path(settings.upload_dir)
    files = db.query(models.File).filter(models.File.uploader_id == user.id).all()
    for f in files:
        blob = upload_dir / f.storage_key
        with contextlib.suppress(OSError):
            blob.unlink(missing_ok=True)
        db.delete(f)

    # Purge private rows.
    db.query(models.WorkspaceMember).filter(
        models.WorkspaceMember.user_id == user.id
    ).delete(synchronize_session=False)
    db.query(models.Notification).filter(
        models.Notification.user_id == user.id
    ).delete(synchronize_session=False)
    db.query(models.AuthSession).filter(
        models.AuthSession.user_id == user.id
    ).delete(synchronize_session=False)

    # Anonymize the surviving user row (shared content keeps its author FK).
    user.display_name = "Deleted user"
    user.email = f"deleted-{user.id}@example.invalid"
    user.hashed_password = None
    user.avatar_url = None
    user.is_active = False

    db.commit()
    _clear_session_cookie(response)
    return {"ok": True, "deleted": True}
