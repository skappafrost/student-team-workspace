"""Task CRUD."""

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import _get_project_or_404, _get_task_or_404, get_current_user
from services import log_activity, notify

router = APIRouter()


@router.get("/users/me/tasks", response_model=list[schemas.MyTaskOut])
async def list_my_tasks(
    due: str | None = Query(
        default=None,
        description="Due-date bucket: overdue | today | week | later | none",
    ),
    status: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """All tasks assigned to the current user across every workspace they belong to."""
    rows = (
        db.query(models.Task, models.Project, models.Workspace)
        .join(models.Project, models.Task.project_id == models.Project.id)
        .join(models.Workspace, models.Project.workspace_id == models.Workspace.id)
        .join(
            models.WorkspaceMember,
            (models.WorkspaceMember.workspace_id == models.Workspace.id)
            & (models.WorkspaceMember.user_id == current_user["id"]),
        )
        .filter(models.Task.assignee_id == current_user["id"])
    )
    if status:
        rows = rows.filter(models.Task.status == status)

    now = datetime.datetime.now(datetime.UTC)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    week_end = today_end + datetime.timedelta(days=7)

    results = []
    for task, project, workspace in rows.all():
        due_at = task.due_at
        if due_at is not None and due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=datetime.UTC)
        if due == "overdue" and not (due_at and due_at < now):
            continue
        if due == "today" and not (due_at and now <= due_at <= today_end):
            continue
        if due == "week" and not (due_at and today_end < due_at <= week_end):
            continue
        if due == "later" and not (due_at and due_at > week_end):
            continue
        if due == "none" and due_at is not None:
            continue
        out = schemas.MyTaskOut(
            **schemas.TaskOut.model_validate(task).model_dump(),
            project_name=project.name,
            workspace_name=workspace.name,
        )
        if out.due_at is not None and out.due_at.tzinfo is None:
            out.due_at = out.due_at.replace(tzinfo=datetime.UTC)
        results.append(out)

    results.sort(key=lambda t: (t.due_at is None, t.due_at or datetime.datetime.max.replace(tzinfo=datetime.UTC)))
    return results


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
        due_at=payload.due_at,
    )
    db.add(task)
    db.flush()
    if task.assignee_id and task.assignee_id != current_user["id"]:
        notify(
            db,
            user_id=task.assignee_id,
            type="task-assigned",
            title=f"Task assigned: {task.title}",
            content=f"You were assigned '{task.title}' in project {project.name}.",
            link=f"/dashboard/projects/{project_id}",
        )
    log_activity(
        db,
        workspace_id=project.workspace_id,
        actor_id=current_user["id"],
        verb="created task",
        target_type="task",
        target_id=task.id,
        target_label=task.title,
    )
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
        if payload.assignee_id != task.assignee_id and payload.assignee_id != current_user["id"]:
            notify(
                db,
                user_id=payload.assignee_id,
                type="task-assigned",
                title=f"Task assigned: {task.title}",
                content=f"You were assigned '{task.title}' in project {project.name}.",
                link=f"/dashboard/projects/{project.id}",
            )
        task.assignee_id = payload.assignee_id
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.status is not None:
        task.status = payload.status
    if payload.position is not None:
        task.position = payload.position
    if payload.due_at is not None:
        task.due_at = payload.due_at

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
