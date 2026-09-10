"""Pydantic schemas for workspace API."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

RoleValue = Literal["owner", "admin", "member", "guest"]


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    description: Optional[str] = Field(default=None, max_length=2000)


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(
        default=None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    description: Optional[str] = Field(default=None, max_length=2000)


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
    avatar_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str]
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
            try:
                data.memberships = data.members
            except Exception:
                pass
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
    accepted_at: Optional[datetime]

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


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: bool = False
    event_type: EventType = "reminder"
    project_id: Optional[str] = None


class EventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    event_type: Optional[EventType] = None
    project_id: Optional[str] = None


class EventOut(BaseModel):
    id: str
    workspace_id: str
    project_id: Optional[str]
    created_by: str
    title: str
    description: Optional[str]
    start_at: datetime
    end_at: Optional[datetime]
    all_day: bool
    event_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = Field(default=None, max_length=50)


class ProjectOut(BaseModel):
    id: str
    workspace_id: str
    owner_id: Optional[str]
    name: str
    description: Optional[str]
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
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    topic: Optional[str] = Field(default=None, max_length=2000)
    type: Optional[ChannelType] = None


class ChannelMemberAdd(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=36)


class ChannelMemberOut(BaseModel):
    channel_id: str
    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    joined_at: Optional[datetime] = None


class ChannelOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    type: str
    created_by: str
    is_private: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    parent_id: Optional[str] = None


class MessageUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1, max_length=5000)


class MessageOut(BaseModel):
    id: str
    channel_id: str
    author_id: str
    author_name: Optional[str] = None
    content: str
    parent_id: Optional[str]
    created_at: datetime
    updated_at: datetime

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
        return {
            "id": data.id,
            "channel_id": data.channel_id,
            "author_id": data.author_id,
            "author_name": author_name,
            "content": data.content,
            "parent_id": data.parent_id,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }


# ---------------------------------------------------------------------------
# Page (Knowledge Base) schemas
# ---------------------------------------------------------------------------
class PageCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    content: Optional[str] = Field(default=None, max_length=50000)
    parent_id: Optional[str] = None


class PageUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    content: Optional[str] = Field(default=None, max_length=50000)
    parent_id: Optional[str] = None


class PageOut(BaseModel):
    id: str
    workspace_id: str
    parent_id: Optional[str]
    title: str
    slug: str
    content: Optional[str]
    created_by: str
    updated_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PageTreeItem(PageOut):
    children: list["PageTreeItem"] = []

    model_config = ConfigDict(from_attributes=True)


TaskStatus = Literal["backlog", "todo", "doing", "done"]
TaskPriority = Literal["low", "medium", "high", "urgent"]

class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    assignee_id: Optional[str] = None
    priority: TaskPriority = "medium"
    status: TaskStatus = "todo"
    position: float = 0.0


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    assignee_id: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    position: Optional[float] = None


class TaskOut(BaseModel):
    id: str
    project_id: str
    assignee_id: Optional[str]
    title: str
    description: Optional[str]
    status: str
    priority: str
    position: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# File schemas
# ---------------------------------------------------------------------------
class FileUpload(BaseModel):
    # Placeholder; actual file is sent as multipart/form-data.
    pass


class FileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=500)


class FileOut(BaseModel):
    id: str
    workspace_id: str
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    message_id: Optional[str] = None
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
    content: Optional[str] = Field(default=None, max_length=5000)


class NotificationUpdate(BaseModel):
    read: bool


class NotificationOut(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    content: Optional[str]
    read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
