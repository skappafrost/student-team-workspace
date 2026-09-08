"""Project CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member, require_permission
from database import get_db
from dependencies import _get_project_or_404, _get_workspace_or_404, get_current_user

router = APIRouter()


@router.post(
    "/workspaces/{workspace_id}/projects", response_model=schemas.ProjectOut, status_code=201
)
async def create_project(
    workspace_id: str,
    payload: schemas.ProjectCreate,
    current_user: dict = Depends(require_permission("project.create")),
    db: Session = Depends(get_db),
):
    """Create a new project inside a workspace. Any member can create."""
    _get_workspace_or_404(db, workspace_id)
    project = models.Project(
        workspace_id=workspace_id,
        owner_id=current_user["id"],
        name=payload.name,
        description=payload.description,
        status="active",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/workspaces/{workspace_id}/projects", response_model=list[schemas.ProjectOut])
async def list_workspace_projects(
    workspace_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all projects in a workspace."""
    _get_workspace_or_404(db, workspace_id)
    _require_member(workspace_id, current_user["id"], db)
    projects = db.query(models.Project).filter(models.Project.workspace_id == workspace_id).all()
    return projects


@router.get("/projects/{project_id}", response_model=schemas.ProjectOut)
async def get_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single project. Must be a workspace member."""
    project = _get_project_or_404(db, project_id)
    _require_member(project.workspace_id, current_user["id"], db)
    return project


@router.patch("/projects/{project_id}", response_model=schemas.ProjectOut)
async def update_project(
    project_id: str,
    payload: schemas.ProjectUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a project. Requires owner/admin or project creator."""
    project = _get_project_or_404(db, project_id)
    membership = _require_member(project.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    is_admin_plus = ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]
    is_creator = project.owner_id == current_user["id"]

    if not (is_admin_plus or is_creator):
        raise HTTPException(status_code=403, detail="Not allowed to update this project")

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.status is not None:
        project.status = payload.status

    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a project. Requires owner/admin."""
    project = _get_project_or_404(db, project_id)
    membership = _require_member(project.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(status_code=403, detail="Not allowed to delete this project")

    db.delete(project)
    db.commit()
    return None
