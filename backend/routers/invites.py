"""Workspace invitation endpoints."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from authorization import Role, require_permission
from database import get_db
from dependencies import _get_workspace_or_404, _utcnow, get_current_user
from email_sender import send_invite_email

router = APIRouter()


@router.post(
    "/workspaces/{workspace_id}/invites", response_model=schemas.InviteOut, status_code=201
)
async def create_invite(
    workspace_id: str,
    payload: schemas.InviteCreate,
    current_user: dict = Depends(require_permission("workspace.invite")),
    db: Session = Depends(get_db),
):
    """Invite a user by email to a workspace. Requires admin or higher role."""
    # RBAC enforced by require_permission dependency
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Prevent duplicate active invite for same email/workspace.
    existing = (
        db.query(models.WorkspaceInvite)
        .filter(
            models.WorkspaceInvite.workspace_id == workspace_id,
            models.WorkspaceInvite.email == payload.email,
            models.WorkspaceInvite.accepted_at.is_(None),
            models.WorkspaceInvite.expires_at > _utcnow(),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Active invite already exists for this email")

    invite = models.WorkspaceInvite(
        workspace_id=workspace_id,
        email=payload.email,
        role=payload.role or Role.MEMBER.value,
        expires_at=_utcnow() + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    send_invite_email(
        email=invite.email,
        token=invite.token,
        workspace_name=workspace.name,
    )
    return invite


@router.post("/invites/accept", response_model=schemas.WorkspaceMembershipOut, status_code=201)
async def accept_invite(
    payload: schemas.InviteAccept,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept an invitation by token and become a workspace member."""
    invite = (
        db.query(models.WorkspaceInvite)
        .filter(models.WorkspaceInvite.token == payload.token)
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Invite already accepted")
    if invite.expires_at < _utcnow():
        raise HTTPException(status_code=410, detail="Invite expired")

    # Mark accepted
    invite.accepted_at = _utcnow()

    # Create membership
    membership = models.WorkspaceMembership(
        workspace_id=invite.workspace_id,
        user_id=current_user["id"],
        role=invite.role,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


@router.get("/workspaces/{workspace_id}/invites", response_model=list[schemas.InviteOut])
async def list_workspace_invites(
    workspace_id: str,
    current_user: dict = Depends(require_permission("workspace.invite")),
    db: Session = Depends(get_db),
):
    """List all pending invitations for a workspace. Requires admin or higher role."""
    _get_workspace_or_404(db, workspace_id)
    invites = (
        db.query(models.WorkspaceInvite)
        .filter(
            models.WorkspaceInvite.workspace_id == workspace_id,
            models.WorkspaceInvite.accepted_at.is_(None),
            models.WorkspaceInvite.expires_at > _utcnow(),
        )
        .all()
    )
    return invites


@router.patch("/workspaces/{workspace_id}/invites/{invite_id}", response_model=schemas.InviteOut)
async def update_invite_role(
    workspace_id: str,
    invite_id: str,
    payload: schemas.InviteRoleUpdate,
    current_user: dict = Depends(require_permission("workspace.invite")),
    db: Session = Depends(get_db),
):
    """Update the role of a pending invitation. Requires admin or higher role."""
    _get_workspace_or_404(db, workspace_id)
    invite = (
        db.query(models.WorkspaceInvite)
        .filter(
            models.WorkspaceInvite.id == invite_id,
            models.WorkspaceInvite.workspace_id == workspace_id,
        )
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=409, detail="Invite already accepted")

    try:
        new_role = Role(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role") from None

    invite.role = new_role.value
    db.commit()
    db.refresh(invite)
    return invite


@router.delete("/workspaces/{workspace_id}/invites/{invite_id}", status_code=204)
async def cancel_invite(
    workspace_id: str,
    invite_id: str,
    current_user: dict = Depends(require_permission("workspace.invite")),
    db: Session = Depends(get_db),
):
    """Cancel a pending invitation. Requires admin or higher role."""
    _get_workspace_or_404(db, workspace_id)
    invite = (
        db.query(models.WorkspaceInvite)
        .filter(
            models.WorkspaceInvite.id == invite_id,
            models.WorkspaceInvite.workspace_id == workspace_id,
        )
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    db.delete(invite)
    db.commit()
    return None
