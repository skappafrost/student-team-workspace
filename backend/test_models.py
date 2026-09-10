"""Database roundtrip tests for SQLAlchemy models and Alembic migration."""

import os
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database import Base
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


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_alembic.db")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


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


def test_model_rejects_duplicate_membership(db_session):
    """A second WorkspaceMember row for the same (workspace, user) raises IntegrityError."""
    user = User(email="dup@example.com", display_name="Dup", hashed_password="x")
    workspace = Workspace(name="WS", slug="ws-dup")
    db_session.add_all([user, workspace])
    db_session.commit()

    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member"))
    db_session.commit()

    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


MIGRATION_DB = os.path.join(os.path.dirname(__file__), "test_stw_migration_t015.db")


def test_migration_dedupes_and_enforces_unique():
    """Round-trip the T015 migration on a seeded db that contains dup rows.

    Scenario: schema at the previous head (101f600f1926), raw-insert duplicate
    workspace_members rows, then upgrade to head. The dedupe pre-step must keep
    the most privileged role (owner > admin > member > guest) and, among equal
    roles, the earliest joined_at. Afterwards the unique constraint must reject
    further duplicates, and downgrade/upgrade must round-trip cleanly.
    """
    db_url = f"sqlite:///{MIGRATION_DB}"
    if os.path.exists(MIGRATION_DB):
        os.remove(MIGRATION_DB)

    cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    os.environ["DATABASE_URL"] = db_url
    try:
        # 1) Schema at the revision BEFORE the T015 unique constraint.
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "101f600f1926")

        # 2) Seed users/workspace plus duplicate memberships.
        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (id, email, display_name, is_active) VALUES "
                "('u1', 'a@example.com', 'A', 1), ('u2', 'b@example.com', 'B', 1)"
            ))
            conn.execute(text(
                "INSERT INTO workspaces (id, name, slug) VALUES ('w1', 'WS', 'ws1')"
            ))
            conn.execute(text(
                "INSERT INTO workspace_members (id, workspace_id, user_id, role, joined_at) VALUES "
                "('m1', 'w1', 'u1', 'member', '2026-01-01 10:00:00'), "
                "('m2', 'w1', 'u1', 'member', '2026-02-01 10:00:00'), "
                "('m3', 'w1', 'u1', 'admin',  '2026-03-01 10:00:00'), "
                "('m4', 'w1', 'u2', 'member', '2026-01-01 10:00:00'), "
                "('m5', 'w1', 'u2', 'member', '2026-02-01 10:00:00')"
            ))

        # 3) Upgrade to head — dedupe then add the unique constraint.
        command.upgrade(cfg, "head")

        # 4) Dedupe kept the most privileged role (u1 -> admin, latest join)
        #    and the earliest joined_at among equal roles (u2 -> 2026-01-01).
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT user_id, role, joined_at FROM workspace_members ORDER BY user_id"
            )).fetchall()
        assert [(r.user_id, r.role, str(r.joined_at)[:19]) for r in rows] == [
            ("u1", "admin", "2026-03-01 10:00:00"),
            ("u2", "member", "2026-01-01 10:00:00"),
        ], rows

        # 5) Unique constraint is now enforced at the DB level.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO workspace_members (id, workspace_id, user_id, role, joined_at) "
                    "VALUES ('m6', 'w1', 'u1', 'guest', '2026-04-01 10:00:00')"
                ))

        # 6) Alembic round-trip: downgrade below the constraint and back up.
        command.downgrade(cfg, "101f600f1926")
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM workspace_members")).scalar()
        assert count == 2
        engine.dispose()
    finally:
        os.environ.pop("DATABASE_URL", None)
        # Windows locks open sqlite files — retry after disposal if still held.
        for _ in range(3):
            try:
                if os.path.exists(MIGRATION_DB):
                    os.remove(MIGRATION_DB)
                break
            except PermissionError:
                import time
                time.sleep(0.2)
