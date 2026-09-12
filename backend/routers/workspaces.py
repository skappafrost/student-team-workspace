"""Workspace CRUD + ownership transfer."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from authorization import Role, _require_member, require_permission
from database import get_db
from dependencies import _get_workspace_or_404, get_current_user

router = APIRouter()


@router.post("/workspaces", response_model=schemas.WorkspaceDetailOut, status_code=201)
async def create_workspace(
    payload: schemas.WorkspaceCreate,
    current_user: dict = Depends(require_permission("workspace.create")),
    db: Session = Depends(get_db),
):
    """Create a new workspace and set the creator as owner."""
    # RBAC enforced by require_permission dependency
    if db.query(models.Workspace).filter(models.Workspace.slug == payload.slug).first():
        raise HTTPException(status_code=409, detail="Workspace slug already exists")

    workspace = models.Workspace(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
    )
    db.add(workspace)
    db.flush()  # get workspace.id

    membership = models.WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=current_user["id"],
        role=Role.OWNER.value,
    )
    db.add(membership)
    db.commit()
    db.refresh(workspace)
    db.refresh(membership)
    workspace.memberships = [membership]
    return workspace


@router.get("/workspaces", response_model=list[schemas.WorkspaceOut])
async def list_workspaces(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List workspaces the current user is a member of."""
    memberships = (
        db.query(models.WorkspaceMembership)
        .filter(models.WorkspaceMembership.user_id == current_user["id"])
        .all()
    )
    workspace_ids = [m.workspace_id for m in memberships]
    if not workspace_ids:
        return []
    workspaces = db.query(models.Workspace).filter(models.Workspace.id.in_(workspace_ids)).all()
    return workspaces


@router.get("/workspaces/{workspace_id}", response_model=schemas.WorkspaceDetailOut)
async def get_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single workspace if the current user is a member."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    return workspace


@router.get("/workspaces/{workspace_id}/activity", response_model=list[schemas.ActivityOut])
async def list_workspace_activity(
    workspace_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recent activity feed for a workspace (members only), newest first."""
    _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    limit = max(1, min(limit, 100))
    rows = (
        db.query(models.Activity, models.User.display_name)
        .join(models.User, models.User.id == models.Activity.actor_id)
        .filter(models.Activity.workspace_id == workspace_id)
        .order_by(models.Activity.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        schemas.ActivityOut(
            id=a.id,
            workspace_id=a.workspace_id,
            actor_id=a.actor_id,
            actor_name=name,
            verb=a.verb,
            target_type=a.target_type,
            target_id=a.target_id,
            target_label=a.target_label,
            created_at=a.created_at,
        )
        for a, name in rows
    ]


@router.patch("/workspaces/{workspace_id}", response_model=schemas.WorkspaceDetailOut)
async def update_workspace(
    workspace_id: str,
    payload: schemas.WorkspaceUpdate,
    current_user: dict = Depends(require_permission("workspace.update")),
    db: Session = Depends(get_db),
):
    """Update a workspace. Requires admin or higher role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    # RBAC enforced by require_permission dependency

    if payload.name is not None:
        workspace.name = payload.name
    if payload.slug is not None:
        if (
            payload.slug != workspace.slug
            and db.query(models.Workspace).filter(models.Workspace.slug == payload.slug).first()
        ):
            raise HTTPException(status_code=409, detail="Workspace slug already exists")
        workspace.slug = payload.slug
    if payload.description is not None:
        workspace.description = payload.description

    db.commit()
    db.refresh(workspace)
    return workspace


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    current_user: dict = Depends(require_permission("workspace.delete")),
    db: Session = Depends(get_db),
):
    """Delete a workspace. Requires owner role."""
    workspace = _get_workspace_or_404(db, workspace_id)
    # RBAC enforced by require_permission dependency
    db.delete(workspace)
    db.commit()
    return None


@router.post("/workspaces/{workspace_id}/transfer-ownership", status_code=200)
async def transfer_ownership(
    workspace_id: str,
    payload: schemas.TransferOwnershipIn,
    current_user: dict = Depends(require_permission("workspace.transfer_ownership")),
    db: Session = Depends(get_db),
):
    """Transfer workspace ownership to another member. Requires owner role."""
    # RBAC enforced by require_permission dependency
    _get_workspace_or_404(db, workspace_id)

    # Get current owner's membership
    current_membership = (
        db.query(models.WorkspaceMembership)
        .filter(
            models.WorkspaceMembership.workspace_id == workspace_id,
            models.WorkspaceMembership.user_id == current_user["id"],
        )
        .first()
    )
    if not current_membership or current_membership.role != Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Only the current owner can transfer ownership")

    # Get target member
    target_membership = (
        db.query(models.WorkspaceMembership)
        .filter(
            models.WorkspaceMembership.workspace_id == workspace_id,
            models.WorkspaceMembership.user_id == payload.user_id,
        )
        .first()
    )
    if not target_membership:
        raise HTTPException(status_code=404, detail="Target member not found")

    # Perform transfer
    current_membership.role = Role.ADMIN.value
    target_membership.role = Role.OWNER.value
    db.commit()
    db.refresh(current_membership)
    db.refresh(target_membership)

    return {
        "message": "Ownership transferred successfully",
        "new_owner_id": target_membership.user_id,
    }
