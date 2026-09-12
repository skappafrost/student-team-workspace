"""Pydantic schemas for workspace API."""

import contextlib
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

RoleValue = Literal["owner", "admin", "member", "guest"]


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str | None = Field(default=None, max_length=2000)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(
        default=None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    description: str | None = Field(default=None, max_length=2000)


class WorkspaceMembershipOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    role: str
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceDetailOut(WorkspaceOut):
    memberships: list[WorkspaceMembershipOut] = []

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _map_members(cls, data):
        if hasattr(data, "members") and not hasattr(data, "memberships"):
            with contextlib.suppress(Exception):
                data.memberships = data.members
        return data


class InviteCreate(BaseModel):
    email: EmailStr
    role: RoleValue = "member"


class InviteOut(BaseModel):
    id: str
    workspace_id: str
    email: str
    role: str
    token: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class InviteAccept(BaseModel):
    token: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Member management schemas
# ---------------------------------------------------------------------------


class MemberRoleUpdate(BaseModel):
    role: RoleValue


class InviteRoleUpdate(BaseModel):
    role: RoleValue


class TransferOwnershipIn(BaseModel):
    user_id: str = Field(..., min_length=1)


class WorkspaceMemberOut(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    role: str
    joined_at: datetime
    user: Optional["UserOut"] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Event schemas
# ---------------------------------------------------------------------------
EventType = Literal["deadline", "exam", "meeting", "reminder"]
Recurrence = Literal["none", "daily", "weekly", "monthly"]


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    start_at: datetime
    end_at: datetime | None = None
    all_day: bool = False
    event_type: EventType = "reminder"
    recurrence: Recurrence = "none"
    project_id: str | None = None


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool | None = None
    event_type: EventType | None = None
    recurrence: Recurrence | None = None
    project_id: str | None = None


class EventOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str | None
    created_by: str
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime | None
    all_day: bool
    event_type: str
    recurrence: str = "none"
    occurrence_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=50)


class ProjectOut(BaseModel):
    id: str
    workspace_id: str
    owner_id: str | None
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Channel / Message schemas
# ---------------------------------------------------------------------------
ChannelType = Literal["general", "project", "private"]


class ChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: ChannelType = "general"


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: ChannelType | None = None


class ChannelOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    type: str
    created_by: str
    is_private: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DMCreate(BaseModel):
    user_id: str = Field(..., min_length=1)


class DMChannelOut(ChannelOut):
    peer_id: str | None = None
    peer_name: str | None = None


class ReactionToggle(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=32)


class ReactionSummary(BaseModel):
    emoji: str
    count: int
    user_ids: list[str]


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    parent_id: str | None = None


class MessageUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=5000)


class MessageOut(BaseModel):
    id: str
    channel_id: str
    author_id: str
    author_name: str | None = None
    content: str
    parent_id: str | None
    created_at: datetime
    updated_at: datetime
    reactions: list[ReactionSummary] = []

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _populate_author_name(cls, data):
        # Handle both SQLAlchemy instances and plain dicts.
        if isinstance(data, dict):
            return data
        if data is None:
            return data
        author_name = None
        if hasattr(data, "author") and data.author is not None:
            author_name = data.author.display_name
        # Preserve any already-set author_name if author wasn't loaded.
        if author_name is None and hasattr(data, "author_name") and data.author_name is not None:
            author_name = data.author_name
        # Aggregate reactions (grouped by emoji) when the relationship is loaded.
        reactions: list[dict] = []
        loaded = getattr(data, "reactions", None)
        if loaded is not None and not isinstance(loaded, (int, str)):
            grouped: dict[str, list[str]] = {}
            for r in loaded:
                grouped.setdefault(r.emoji, []).append(r.user_id)
            reactions = [
                {"emoji": emoji, "count": len(uids), "user_ids": uids}
                for emoji, uids in grouped.items()
            ]
        return {
            "id": data.id,
            "channel_id": data.channel_id,
            "author_id": data.author_id,
            "author_name": author_name,
            "content": data.content,
            "parent_id": data.parent_id,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
            "reactions": reactions,
        }


# ---------------------------------------------------------------------------
# Page (Knowledge Base) schemas
# ---------------------------------------------------------------------------
class PageCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    content: str | None = Field(default=None, max_length=50000)
    parent_id: str | None = None


class PageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(
        default=None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    content: str | None = Field(default=None, max_length=50000)
    parent_id: str | None = None


class PageOut(BaseModel):
    id: str
    workspace_id: str
    parent_id: str | None
    title: str
    slug: str
    content: str | None
    created_by: str
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PageVersionOut(BaseModel):
    id: str
    page_id: str
    version: int
    title: str
    content: str | None
    author_id: str | None
    author_name: str | None = None
    created_at: datetime


class PageTreeItem(PageOut):
    children: list["PageTreeItem"] = []

    model_config = ConfigDict(from_attributes=True)


TaskStatus = Literal["backlog", "todo", "doing", "done"]
TaskPriority = Literal["low", "medium", "high", "urgent"]


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    assignee_id: str | None = None
    priority: TaskPriority = "medium"
    status: TaskStatus = "todo"
    position: float = 0.0
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    assignee_id: str | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    position: float | None = None
    due_at: datetime | None = None


class TaskOut(BaseModel):
    id: str
    project_id: str
    assignee_id: str | None
    title: str
    description: str | None
    status: str
    priority: str
    position: float
    due_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MyTaskOut(TaskOut):
    """TaskOut enriched with project/workspace names for cross-workspace views."""

    project_name: str
    workspace_name: str


# ---------------------------------------------------------------------------
# File schemas
# ---------------------------------------------------------------------------
class FileUpload(BaseModel):
    # Placeholder; actual file is sent as multipart/form-data.
    pass


class FileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    project_id: str | None = None
    task_id: str | None = None
    message_id: str | None = None


class FileOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    task_id: str | None = None
    message_id: str | None = None
    name: str
    type: str
    size: int
    url: str
    uploaded_by: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Notification schemas
# ---------------------------------------------------------------------------
NotificationType = Literal[
    "file-upload",
    "mention",
    "task-assigned",
    "workspace-invite",
    "message",
    "other",
]


class NotificationCreate(BaseModel):
    user_id: str = Field(..., min_length=1)
    type: NotificationType
    title: str = Field(..., min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=5000)


class NotificationUpdate(BaseModel):
    read: bool


class NotificationOut(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    content: str | None
    link: str | None = None
    read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActivityOut(BaseModel):
    id: str
    workspace_id: str
    actor_id: str
    actor_name: str
    verb: str
    target_type: str
    target_id: str
    target_label: str | None
    created_at: datetime
