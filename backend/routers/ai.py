"""AI assist endpoints (summarize, search)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

import ai_assist
from database import get_db
from dependencies import get_current_user

router = APIRouter()


class SummarizeRequest(BaseModel):
    kind: str
    ref_id: str


class SummarizeResponse(BaseModel):
    summary: str


class SearchResponse(BaseModel):
    results: list[dict]


@router.post("/ai/summarize", response_model=SummarizeResponse)
async def ai_summarize(
    payload: SummarizeRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a summary for a task, page, or channel."""
    kind = payload.kind
    ref_id = payload.ref_id
    user_id = current_user["id"]

    if kind == "task":
        result = ai_assist.summarize_task(db, ref_id, user_id)
    elif kind == "page":
        result = ai_assist.summarize_page(db, ref_id, user_id)
    elif kind == "channel":
        result = ai_assist.summarize_channel(db, ref_id, user_id)
    else:
        raise HTTPException(status_code=422, detail="Invalid kind. Must be task, page, or channel.")

    return {"summary": result["summary"]}


@router.get("/ai/search", response_model=SearchResponse)
async def ai_search(
    q: str = Query(..., min_length=1),
    scope: str = Query("tasks,pages,messages"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search across tasks, pages, and messages in workspaces the user can access."""
    scope_list = [s.strip() for s in scope.split(",") if s.strip()]
    results = ai_assist.search_workspace(db, current_user["id"], q, scope_list)

    return {
        "results": [
            {
                "kind": r.kind,
                "id": r.id,
                "title": r.title,
                "snippet": r.snippet,
                "workspace_id": r.workspace_id,
                "score": r.score,
            }
            for r in results
        ]
    }
