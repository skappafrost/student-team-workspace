"""File upload / management endpoints + upload-dir config."""

import mimetypes
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi import File as FileParam
from sqlalchemy.orm import Session

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import _get_file_or_404, _get_workspace_or_404, get_current_user

router = APIRouter()

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
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


@router.post("/workspaces/{workspace_id}/files", status_code=201)
async def upload_file(
    workspace_id: str,
    file: UploadFile = FileParam(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file to a workspace. Requires member role or higher."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot upload files")

    if not file.filename:
        raise HTTPException(status_code=422, detail="File name is required")

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
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List files in a workspace. Members can view."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view files")

    files = (
        db.query(models.File)
        .filter(models.File.workspace_id == workspace_id)
        .order_by(models.File.created_at.desc())
        .all()
    )
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
