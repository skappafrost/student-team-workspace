"""Wiki / knowledge-base page CRUD."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from database import get_db
from dependencies import _get_page_or_404, _get_workspace_or_404, get_current_user
from services import log_activity

router = APIRouter()


def _validate_parent_id(
    db: Session, workspace_id: str, parent_id: str, page_id: str | None = None
) -> None:
    parent = _get_page_or_404(db, parent_id)
    if parent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Parent page not found in workspace")
    if page_id is not None and parent.id == page_id:
        raise HTTPException(status_code=400, detail="Page cannot be its own parent")


def _check_page_write_permission(
    page: models.Page, membership: models.WorkspaceMembership, current_user: dict
) -> bool:
    user_role_value = membership.role
    user_role = Role(user_role_value) if user_role_value in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]:
        return True
    return page.created_by == current_user["id"]


@router.post("/workspaces/{workspace_id}/pages", response_model=schemas.PageOut, status_code=201)
async def create_page(
    workspace_id: str,
    payload: schemas.PageCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new page in a workspace. Requires member role or higher."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot create pages")

    if payload.parent_id:
        _validate_parent_id(db, workspace_id, payload.parent_id)

    # Slug uniqueness within workspace
    existing = (
        db.query(models.Page)
        .filter(
            models.Page.workspace_id == workspace_id,
            models.Page.slug == payload.slug,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Page slug already exists in this workspace")

    page = models.Page(
        workspace_id=workspace_id,
        parent_id=payload.parent_id,
        title=payload.title,
        slug=payload.slug,
        content=payload.content,
        created_by=current_user["id"],
        updated_by=current_user["id"],
    )
    db.add(page)
    db.flush()
    log_activity(
        db,
        workspace_id=workspace_id,
        actor_id=current_user["id"],
        verb="created page",
        target_type="page",
        target_id=page.id,
        target_label=page.title,
    )
    db.commit()
    db.refresh(page)
    return page


@router.get("/workspaces/{workspace_id}/pages", response_model=list[schemas.PageTreeItem])
async def list_workspace_pages(
    workspace_id: str,
    flat: bool = False,
    search: str | None = None,
    recent: bool = False,
    limit: int = Query(default=10, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List pages in a workspace as a tree or flat list.

    Query params:
      - search: filter title/content by ILIKE (case-insensitive, flat list only).
      - recent: order by updated_at desc and return up to ``limit`` pages (flat).
      - limit: maximum number of recent/search results to return (default 10, max 100).
    """
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view pages")

    query = db.query(models.Page).filter(models.Page.workspace_id == workspace_id)

    if search is not None:
        term = search.strip()
        if not term:
            return []
        like_term = f"%{term}%"
        query = query.filter(
            or_(models.Page.title.ilike(like_term), models.Page.content.ilike(like_term))
        ).order_by(models.Page.updated_at.desc())
        return query.all()

    if recent:
        return query.order_by(models.Page.updated_at.desc()).limit(limit).all()

    pages = query.order_by(models.Page.created_at.asc()).all()

    if flat:
        return pages

    # Build tree: only root pages with nested children loaded lazily; build recursively
    root_pages = [p for p in pages if p.parent_id is None]
    return root_pages


@router.get("/workspaces/{workspace_id}/pages/{page_id}", response_model=schemas.PageOut)
async def get_page(
    workspace_id: str,
    page_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single page. Must be a workspace member."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view pages")

    page = _get_page_or_404(db, page_id)
    if page.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Page not found in workspace")
    return page


@router.patch("/workspaces/{workspace_id}/pages/{page_id}", response_model=schemas.PageOut)
async def update_page(
    workspace_id: str,
    page_id: str,
    payload: schemas.PageUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a page. Requires creator or admin/owner."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    page = _get_page_or_404(db, page_id)
    if page.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Page not found in workspace")

    if not _check_page_write_permission(page, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to update this page")

    if payload.parent_id is not None:
        if payload.parent_id:
            _validate_parent_id(db, workspace_id, payload.parent_id, page_id=page.id)
        page.parent_id = payload.parent_id

    if payload.title is not None:
        page.title = payload.title
    if payload.slug is not None:
        # Slug uniqueness within workspace
        existing = (
            db.query(models.Page)
            .filter(
                models.Page.workspace_id == workspace_id,
                models.Page.slug == payload.slug,
            )
            .first()
        )
        if existing and existing.id != page.id:
            raise HTTPException(
                status_code=409, detail="Page slug already exists in this workspace"
            )
        page.slug = payload.slug
    if payload.content is not None:
        page.content = payload.content

    page.updated_by = current_user["id"]
    db.commit()
    db.refresh(page)
    return page


@router.delete("/workspaces/{workspace_id}/pages/{page_id}", status_code=204)
async def delete_page(
    workspace_id: str,
    page_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a page. Requires admin/owner."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    page = _get_page_or_404(db, page_id)
    if page.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Page not found in workspace")

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(status_code=403, detail="Only admins can delete pages")

    db.delete(page)
    db.commit()
    return None
