"""Task CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import _get_project_or_404, _get_task_or_404, get_current_user

router = APIRouter()


@router.post("/projects/{project_id}/tasks", response_model=schemas.TaskOut, status_code=201)
async def create_task(
    project_id: str,
    payload: schemas.TaskCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new task inside a project. Any workspace member can create."""
    project = _get_project_or_404(db, project_id)
    _require_member(project.workspace_id, current_user["id"], db)

    task = models.Task(
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        assignee_id=payload.assignee_id,
        priority=payload.priority,
        status=payload.status,
        position=payload.position,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/projects/{project_id}/tasks", response_model=list[schemas.TaskOut])
async def list_project_tasks(
    project_id: str,
    status: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tasks in a project, optionally filtered by status."""
    project = _get_project_or_404(db, project_id)
    _require_member(project.workspace_id, current_user["id"], db)

    query = db.query(models.Task).filter(models.Task.project_id == project_id)
    if status:
        query = query.filter(models.Task.status == status)
    tasks = query.order_by(models.Task.position.asc(), models.Task.created_at.asc()).all()
    return tasks


@router.patch("/tasks/{task_id}", response_model=schemas.TaskOut)
async def update_task(
    task_id: str,
    payload: schemas.TaskUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a task (incl. status/column move + assignee). Any workspace member can update."""
    task = _get_task_or_404(db, task_id)
    project = _get_project_or_404(db, task.project_id)
    _require_member(project.workspace_id, current_user["id"], db)

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.assignee_id is not None:
        task.assignee_id = payload.assignee_id
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.status is not None:
        task.status = payload.status
    if payload.position is not None:
        task.position = payload.position

    db.commit()
    db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a task. Requires owner/admin or task creator."""
    task = _get_task_or_404(db, task_id)
    project = _get_project_or_404(db, task.project_id)
    membership = _require_member(project.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    is_admin_plus = ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]
    is_creator = (
        task.assignee_id == current_user["id"] or task.project.owner_id == current_user["id"]
    )

    if not (is_admin_plus or is_creator):
        raise HTTPException(status_code=403, detail="Not allowed to delete this task")

    db.delete(task)
    db.commit()
    return None
