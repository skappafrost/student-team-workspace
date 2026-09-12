"""File upload / management endpoints + upload-dir config."""

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi import File as FileParam
from sqlalchemy.orm import Session

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from config import settings
from database import get_db
from dependencies import (
    _get_channel_or_404,
    _get_file_or_404,
    _get_message_or_404,
    _get_project_or_404,
    _get_task_or_404,
    _get_workspace_or_404,
    get_current_user,
)

router = APIRouter()

UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _file_type(mime_type: str | None) -> str:
    if not mime_type:
        return "other"
    if mime_type.startswith("image/"):
        return "image"
    if (
        mime_type in ("application/pdf",)
        or mime_type.startswith("text/")
        or "document" in mime_type
    ):
        return "document"
    return "other"


def _file_out(file: models.File) -> dict:
    return {
        "id": file.id,
        "workspace_id": file.workspace_id,
        "project_id": file.project_id,
        "task_id": file.task_id,
        "message_id": file.message_id,
        "name": file.original_name,
        "type": _file_type(file.mime_type),
        "size": file.size_bytes,
        "url": f"/uploads/{file.storage_key}",
        "uploaded_by": file.uploader_id,
        "created_at": file.created_at,
    }


def _can_modify_file(
    file: models.File, membership: models.WorkspaceMembership, current_user: dict
) -> bool:
    user_role_value = membership.role
    user_role = Role(user_role_value) if user_role_value in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]:
        return True
    return file.uploader_id == current_user["id"]


def _validate_link_targets(
    db: Session,
    workspace_id: str,
    project_id: str | None,
    task_id: str | None,
    message_id: str | None,
) -> None:
    """Ensure linked resources exist and belong to the same workspace."""
    if project_id is not None:
        project = _get_project_or_404(db, project_id)
        if project.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="Project is not in this workspace")
    if task_id is not None:
        task = _get_task_or_404(db, task_id)
        task_project = _get_project_or_404(db, task.project_id)
        if task_project.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="Task is not in this workspace")
    if message_id is not None:
        message = _get_message_or_404(db, message_id)
        channel = _get_channel_or_404(db, message.channel_id)
        if channel.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="Message is not in this workspace")


@router.post("/workspaces/{workspace_id}/files", status_code=201)
async def upload_file(
    workspace_id: str,
    file: UploadFile = FileParam(...),
    project_id: str | None = Form(None),
    task_id: str | None = Form(None),
    message_id: str | None = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file to a workspace, optionally linked to a project/task/message."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot upload files")

    if not file.filename:
        raise HTTPException(status_code=422, detail="File name is required")

    _validate_link_targets(db, workspace_id, project_id, task_id, message_id)

    content = await file.read()
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=422, detail="File is empty")

    mime_type = (
        file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    )
    storage_key = f"{uuid.uuid4()}_{file.filename}"
    file_path = UPLOAD_DIR / storage_key
    file_path.write_bytes(content)

    db_file = models.File(
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        message_id=message_id,
        uploader_id=current_user["id"],
        original_name=file.filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size,
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    # Emit a notification for the uploader about the successful upload.
    notification = models.Notification(
        user_id=current_user["id"],
        type="file-upload",
        title="File uploaded",
        content=f"Your file {file.filename} was uploaded successfully.",
    )
    db.add(notification)
    db.commit()

    return _file_out(db_file)


@router.get("/workspaces/{workspace_id}/files")
async def list_workspace_files(
    workspace_id: str,
    project_id: str | None = None,
    task_id: str | None = None,
    message_id: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List files in a workspace, optionally filtered by linked resource."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view files")

    query = db.query(models.File).filter(models.File.workspace_id == workspace_id)
    if project_id is not None:
        query = query.filter(models.File.project_id == project_id)
    if task_id is not None:
        query = query.filter(models.File.task_id == task_id)
    if message_id is not None:
        query = query.filter(models.File.message_id == message_id)
    files = query.order_by(models.File.created_at.desc()).all()
    return [_file_out(f) for f in files]


@router.get("/files/{file_id}")
async def get_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single file. Must be a workspace member."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view files")

    return _file_out(file)


@router.patch("/files/{file_id}")
async def update_file(
    file_id: str,
    payload: schemas.FileUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a file's metadata. Requires creator or admin/owner."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    if not _can_modify_file(file, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to update this file")

    if payload.name is not None:
        file.original_name = payload.name
    if (
        payload.project_id is not None
        or payload.task_id is not None
        or payload.message_id is not None
    ):
        _validate_link_targets(
            db, file.workspace_id, payload.project_id, payload.task_id, payload.message_id
        )
        if payload.project_id is not None:
            file.project_id = payload.project_id
        if payload.task_id is not None:
            file.task_id = payload.task_id
        if payload.message_id is not None:
            file.message_id = payload.message_id

    db.commit()
    db.refresh(file)
    return _file_out(file)


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a file. Requires admin/owner."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(status_code=403, detail="Only admins can delete files")

    storage_path = UPLOAD_DIR / file.storage_key
    if storage_path.exists():
        storage_path.unlink()

    db.delete(file)
    db.commit()
    return None
