"""Calendar event CRUD."""

import calendar
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import (
    _get_event_or_404,
    _get_project_or_404,
    _get_workspace_or_404,
    get_current_user,
)
from services import log_activity

router = APIRouter()


def _can_modify_event(
    event: models.Event, membership: models.WorkspaceMembership, current_user: dict
) -> bool:
    if event.created_by == current_user["id"]:
        return True
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    return ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]


@router.post("/workspaces/{workspace_id}/events", response_model=schemas.EventOut, status_code=201)
async def create_event(
    workspace_id: str,
    payload: schemas.EventCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new event in a workspace. Any member can create."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot create events")

    if payload.project_id:
        project = _get_project_or_404(db, payload.project_id)
        if project.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Project not found in workspace")

    event = models.Event(
        workspace_id=workspace_id,
        project_id=payload.project_id,
        created_by=current_user["id"],
        title=payload.title,
        description=payload.description,
        start_at=payload.start_at,
        end_at=payload.end_at,
        all_day=payload.all_day,
        event_type=payload.event_type,
        recurrence=payload.recurrence,
    )
    db.add(event)
    db.flush()
    log_activity(
        db,
        workspace_id=workspace_id,
        actor_id=current_user["id"],
        verb="created event",
        target_type="event",
        target_id=event.id,
        target_label=event.title,
    )
    db.commit()
    db.refresh(event)
    return event


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _expand_occurrences(
    event: models.Event,
    range_start: datetime | None,
    range_end: datetime | None,
    cap: int = 200,
) -> list[schemas.EventOut]:
    """Expand a recurring event into concrete occurrences intersecting the range.

    RRULE-lite: daily / weekly / monthly steps from the base start_at.
    """
    base = schemas.EventOut.model_validate(event)
    if event.recurrence in (None, "none") or range_start is None or range_end is None:
        return [base]

    duration = (event.end_at - event.start_at) if event.end_at else None

    def step(dt: datetime) -> datetime:
        if event.recurrence == "daily":
            return dt + timedelta(days=1)
        if event.recurrence == "weekly":
            return dt + timedelta(weeks=1)
        return _add_months(dt, 1)

    out: list[schemas.EventOut] = []
    start_at = event.start_at
    while start_at <= range_end and len(out) < cap:
        occ_end = start_at + duration if duration else None
        if (occ_end is None or occ_end >= range_start) and start_at >= range_start or start_at < range_start and occ_end is not None and occ_end >= range_start:
            out.append(
                base.model_copy(
                    update={
                        "start_at": start_at,
                        "end_at": occ_end,
                        "occurrence_id": f"{event.id}@{start_at.date().isoformat()}",
                    }
                )
            )
        start_at = step(start_at)
    return out


@router.get("/workspaces/{workspace_id}/events", response_model=list[schemas.EventOut])
async def list_workspace_events(
    workspace_id: str,
    start: str | None = None,
    end: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List events in a workspace, optionally filtered by start/end date range.

    With a range, recurring events are expanded into per-occurrence instances
    (occurrence_id set); without a range the base events are returned as-is.
    """
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view events")

    start_dt = end_dt = None
    if start:
        try:
            start_dt = datetime.fromisoformat(start).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid start date format") from None
    if end:
        try:
            end_dt = datetime.fromisoformat(end).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid end date format") from None

    base_query = db.query(models.Event).filter(models.Event.workspace_id == workspace_id)

    # Non-recurring events: overlap filter in SQL as before.
    query = base_query.filter(
        or_(models.Event.recurrence.is_(None), models.Event.recurrence == "none")
    )
    if start_dt:
        query = query.filter(
            or_(
                models.Event.end_at.is_(None),
                models.Event.end_at >= start_dt,
            )
        )
    if end_dt:
        query = query.filter(models.Event.start_at <= end_dt)
    plain = query.order_by(models.Event.start_at.asc()).all()

    results: list[schemas.EventOut] = [schemas.EventOut.model_validate(e) for e in plain]

    # Recurring events: expand into occurrences (only meaningful with a range).
    recurring = base_query.filter(
        models.Event.recurrence.isnot(None), models.Event.recurrence != "none"
    ).all()
    for event in recurring:
        results.extend(_expand_occurrences(event, start_dt, end_dt))

    results.sort(key=lambda e: e.start_at)
    return results


@router.get("/events/{event_id}", response_model=schemas.EventOut)
async def get_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single event. Must be a workspace member."""
    event = _get_event_or_404(db, event_id)
    membership = _require_member(event.workspace_id, current_user["id"], db)
    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view events")
    return event


@router.patch("/events/{event_id}", response_model=schemas.EventOut)
async def update_event(
    event_id: str,
    payload: schemas.EventUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an event. Requires creator/admin/owner."""
    event = _get_event_or_404(db, event_id)
    membership = _require_member(event.workspace_id, current_user["id"], db)

    if not _can_modify_event(event, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to update this event")

    if payload.title is not None:
        event.title = payload.title
    if payload.description is not None:
        event.description = payload.description
    if payload.start_at is not None:
        event.start_at = payload.start_at
    if payload.end_at is not None:
        event.end_at = payload.end_at
    if payload.all_day is not None:
        event.all_day = payload.all_day
    if payload.event_type is not None:
        event.event_type = payload.event_type
    if payload.recurrence is not None:
        event.recurrence = payload.recurrence
    if payload.project_id is not None:
        if payload.project_id:
            project = _get_project_or_404(db, payload.project_id)
            if project.workspace_id != event.workspace_id:
                raise HTTPException(status_code=404, detail="Project not found in workspace")
        event.project_id = payload.project_id

    db.commit()
    db.refresh(event)
    return event


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an event. Requires creator/admin/owner."""
    event = _get_event_or_404(db, event_id)
    membership = _require_member(event.workspace_id, current_user["id"], db)

    if not _can_modify_event(event, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to delete this event")

    db.delete(event)
    db.commit()
    return None
