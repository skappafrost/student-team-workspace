"""AI-assist helpers: pluggable provider interface + deterministic fallback.

No external LLM key is required. The provider layer is structured so a real LLM
can be plugged in later via environment variables without changing the API.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models


class ProviderNotConfiguredError(Exception):
    """Raised when no external LLM provider is configured."""

    pass


def _provider_config() -> dict[str, Any] | None:
    """Return active provider config from env, or None if not configured."""
    api_key = os.getenv("AI_PROVIDER_API_KEY")
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "base_url": os.getenv("AI_PROVIDER_BASE_URL"),
        "model": os.getenv("AI_PROVIDER_MODEL", "gpt-4o-mini"),
    }


def summarize_via_provider(kind: str, ref_id: str, text: str) -> str:
    """Attempt to summarize via an external LLM provider.

    Raises ProviderNotConfiguredError if no provider is configured, allowing
    callers to fall back to deterministic extractive summary.
    """
    config = _provider_config()
    if not config:
        raise ProviderNotConfiguredError("No AI provider configured")
    # Real LLM call would go here; for now the app always uses fallback.
    raise ProviderNotConfiguredError("Provider not yet implemented")


def _split_sentences(text: str, max_sentences: int = 3) -> list[str]:
    """Naive sentence splitter for deterministic fallback."""
    if not text:
        return []
    # Split on sentence-ending punctuation followed by whitespace or end.
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in raw if s.strip()]
    return sentences[:max_sentences]


def _extractive_summary(text: str, max_sentences: int = 3) -> str:
    """Return the first few sentences of *text* as a fallback summary."""
    sentences = _split_sentences(text or "", max_sentences=max_sentences)
    if not sentences:
        return "No content available to summarize."
    return " ".join(sentences)


# ---------------------------------------------------------------------------
# Domain summarizers
# ---------------------------------------------------------------------------


def summarize_task(db: Session, task_id: str, user_id: str) -> dict:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    project = db.query(models.Project).filter(models.Project.id == task.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    membership = (
        db.query(models.WorkspaceMember)
        .filter(
            models.WorkspaceMember.workspace_id == project.workspace_id,
            models.WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not allowed to access this task")

    content = f"Task: {task.title}. {task.description or ''}".strip()
    try:
        summary = summarize_via_provider("task", task.id, content)
    except ProviderNotConfiguredError:
        summary = _extractive_summary(content)

    return {"summary": summary}


def summarize_page(db: Session, page_id: str, user_id: str) -> dict:
    page = db.query(models.Page).filter(models.Page.id == page_id).first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    membership = (
        db.query(models.WorkspaceMember)
        .filter(
            models.WorkspaceMember.workspace_id == page.workspace_id,
            models.WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not allowed to access this page")

    content = f"Page: {page.title}. {page.content or ''}".strip()
    try:
        summary = summarize_via_provider("page", page.id, content)
    except ProviderNotConfiguredError:
        summary = _extractive_summary(content)

    return {"summary": summary}


def summarize_channel(db: Session, channel_id: str, user_id: str) -> dict:
    channel = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    membership = (
        db.query(models.WorkspaceMember)
        .filter(
            models.WorkspaceMember.workspace_id == channel.workspace_id,
            models.WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not allowed to access this channel")

    # Build a transcript from recent messages (chronological).
    messages = (
        db.query(models.Message)
        .filter(models.Message.channel_id == channel_id)
        .order_by(models.Message.created_at.asc())
        .all()
    )
    message_text = " ".join(m.content for m in messages if m.content)
    content = f"Channel: {channel.name}. {message_text}".strip()

    try:
        summary = summarize_via_provider("channel", channel.id, content)
    except ProviderNotConfiguredError:
        summary = _extractive_summary(content)

    return {"summary": summary}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    kind: str
    id: str
    title: str
    snippet: str
    workspace_id: str
    score: float


def _score(query: str, title: str, content: str | None) -> float:
    """Very simple keyword relevance score.

    Title matches are weighted higher than body matches.
    """
    q = query.lower()
    title_lower = (title or "").lower()
    content_lower = (content or "").lower()

    score = 0.0
    if q in title_lower:
        score += 10.0
        score += title_lower.count(q) * 2
    if q in content_lower:
        score += 3.0
        score += content_lower.count(q) * 0.5
    return score


def search_workspace(
    db: Session,
    user_id: str,
    query: str,
    scope: list[str],
) -> list[SearchResult]:
    """Return keyword search results the user can access.

    Searches across tasks, pages and messages. Results are filtered by workspace
    membership and ordered by a simple keyword score (higher = better match).
    """
    if not query or not query.strip():
        return []

    q = query.strip()
    results: list[SearchResult] = []

    # Build a set of workspace IDs the user belongs to.
    memberships = (
        db.query(models.WorkspaceMember).filter(models.WorkspaceMember.user_id == user_id).all()
    )
    workspace_ids = {m.workspace_id for m in memberships}

    if "tasks" in scope:
        tasks = (
            db.query(models.Task)
            .join(models.Project, models.Task.project_id == models.Project.id)
            .filter(models.Project.workspace_id.in_(workspace_ids))
            .all()
        )
        for task in tasks:
            score = _score(q, task.title, task.description)
            if score > 0:
                results.append(
                    SearchResult(
                        kind="task",
                        id=task.id,
                        title=task.title,
                        snippet=(task.description or "")[:200],
                        workspace_id=task.project.workspace_id,
                        score=score,
                    )
                )

    if "pages" in scope:
        pages = db.query(models.Page).filter(models.Page.workspace_id.in_(workspace_ids)).all()
        for page in pages:
            score = _score(q, page.title, page.content)
            if score > 0:
                results.append(
                    SearchResult(
                        kind="page",
                        id=page.id,
                        title=page.title,
                        snippet=(page.content or "")[:200],
                        workspace_id=page.workspace_id,
                        score=score,
                    )
                )

    if "messages" in scope:
        messages = (
            db.query(models.Message)
            .join(models.Channel, models.Message.channel_id == models.Channel.id)
            .filter(models.Channel.workspace_id.in_(workspace_ids))
            .all()
        )
        for message in messages:
            score = _score(q, "", message.content)
            if score > 0:
                results.append(
                    SearchResult(
                        kind="message",
                        id=message.id,
                        title=f"Message in {message.channel.name}",
                        snippet=(message.content or "")[:200],
                        workspace_id=message.channel.workspace_id,
                        score=score,
                    )
                )

    results.sort(key=lambda r: r.score, reverse=True)
    return results
