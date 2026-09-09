"""Database roundtrip tests for SQLAlchemy models and Alembic migration."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from models import (
    Channel,
    Document,
    Event,
    File,
    Message,
    Project,
    Task,
    TaskComment,
    User,
    Workspace,
    WorkspaceMember,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_models_roundtrip_one_row_per_table(db_session):
    """Insert and query one row per schema table."""
    user = User(email="alice@example.com", display_name="Alice", hashed_password="x")
    workspace = Workspace(name="WS", slug="ws", description="A workspace")
    db_session.add_all([user, workspace])
    db_session.commit()

    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
    project = Project(
        workspace_id=workspace.id,
        owner_id=user.id,
        name="P1",
        description="Project one",
        status="active",
    )
    channel = Channel(workspace_id=workspace.id, name="general", is_private=False, created_by=user.id, type="general")
    document = Document(
        workspace_id=workspace.id,
        project_id=None,
        author_id=user.id,
        title="Doc",
        content="content",
    )
    event = Event(
        workspace_id=workspace.id,
        project_id=None,
        title="Event",
        start_at=_utc_now(),
        created_by=user.id,
    )
    db_session.add_all([member, project, channel, document, event])
    db_session.commit()

    task = Task(
        project_id=project.id,
        assignee_id=user.id,
        title="Task",
        description="desc",
        status="todo",
        priority="medium",
    )
    db_session.add(task)
    db_session.commit()

    comment = TaskComment(task_id=task.id, author_id=user.id, content="nice")
    message = Message(channel_id=channel.id, author_id=user.id, content="hello")
    db_session.add_all([comment, message])
    db_session.commit()

    file_ = File(
        workspace_id=workspace.id,
        project_id=project.id,
        task_id=task.id,
        message_id=message.id,
        uploader_id=user.id,
        original_name="file.txt",
        storage_key="key",
        mime_type="text/plain",
        size_bytes=1,
    )
    db_session.add(file_)
    db_session.commit()

    # Query and assert one row per table
    assert db_session.query(User).one().email == "alice@example.com"
    assert db_session.query(Workspace).one().slug == "ws"
    assert db_session.query(WorkspaceMember).one().role == "owner"
    assert db_session.query(Project).one().name == "P1"
    assert db_session.query(Task).one().title == "Task"
    assert db_session.query(TaskComment).one().content == "nice"
    assert db_session.query(Channel).one().name == "general"
    assert db_session.query(Message).one().content == "hello"
    assert db_session.query(Document).one().title == "Doc"
    assert db_session.query(File).one().original_name == "file.txt"
    assert db_session.query(Event).one().title == "Event"


def test_alembic_migration_creates_all_tables(db_session):
    """Ensure Alembic-style schema contains every expected table."""
    engine = db_session.bind
    tables = {"users", "workspaces", "workspace_members", "projects", "tasks",
              "task_comments", "channels", "messages", "documents", "files", "events"}
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        existing = {row[0] for row in result}
    assert tables.issubset(existing)
