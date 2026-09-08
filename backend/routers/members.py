"""Workspace member management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

import models
import schemas
from authorization import Role, require_permission
from database import get_db
from dependencies import _get_workspace_or_404

router = APIRouter()


@router.get("/workspaces/{workspace_id}/members", response_model=list[schemas.WorkspaceMemberOut])
async def list_workspace_members(
    workspace_id: str,
    current_user: dict = Depends(require_permission("workspace.manage_members")),
    db: Session = Depends(get_db),
):
    """List all members of a workspace. Requires admin or higher role."""
    # RBAC enforced by require_permission dependency
    _get_workspace_or_404(db, workspace_id)
    members = (
        db.query(models.WorkspaceMembership)
        .options(selectinload(models.WorkspaceMembership.user))
        .filter(models.WorkspaceMembership.workspace_id == workspace_id)
        .all()
    )
    return members


@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}", response_model=schemas.WorkspaceMemberOut
)
async def update_member_role(
    workspace_id: str,
    user_id: str,
    payload: schemas.MemberRoleUpdate,
    current_user: dict = Depends(require_permission("member.update_role")),
    db: Session = Depends(get_db),
):
    """Update a member's role. Requires admin or higher role. Cannot change owner role."""
    # RBAC enforced by require_permission dependency
    _get_workspace_or_404(db, workspace_id)

    membership = (
        db.query(models.WorkspaceMembership)
        .filter(
            models.WorkspaceMembership.workspace_id == workspace_id,
            models.WorkspaceMembership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    # Prevent changing owner's role
    if membership.role == Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Cannot change owner's role")

    # Prevent self-demotion from owner
    if membership.user_id == current_user["id"] and membership.role == Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Cannot change your own role as owner")

    # Validate role
    try:
        new_role = Role(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role") from None

    membership.role = new_role.value
    db.commit()
    db.refresh(membership)
    return membership


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(
    workspace_id: str,
    user_id: str,
    current_user: dict = Depends(require_permission("member.remove")),
    db: Session = Depends(get_db),
):
    """Remove a member from the workspace. Requires admin or higher role. Cannot remove owner."""
    # RBAC enforced by require_permission dependency
    _get_workspace_or_404(db, workspace_id)

    membership = (
        db.query(models.WorkspaceMembership)
        .filter(
            models.WorkspaceMembership.workspace_id == workspace_id,
            models.WorkspaceMembership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    # Prevent removing owner
    if membership.role == Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Cannot remove workspace owner")

    # Prevent self-removal if owner
    if membership.user_id == current_user["id"] and membership.role == Role.OWNER.value:
        raise HTTPException(status_code=403, detail="Cannot remove yourself as owner")

    db.delete(membership)
    db.commit()
    return None
