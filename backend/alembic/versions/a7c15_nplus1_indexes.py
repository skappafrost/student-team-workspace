"""TA5-1: indexes for hot FK columns used in list-endpoint WHERE/JOINs.

Audit (backend/routers + ai_assist) found these FK columns filtered per
request with no supporting index. UNIQUE constraints already cover the
leftmost column of composite uniques (workspace_members.workspace_id,
channel_members.channel_id), so only the non-covered columns appear here.
``messages.channel_id`` is indexed composite with ``created_at`` because
GET /channels/{id}/messages filters on the former and sorts on the latter.

All statements are plain CREATE/DROP INDEX — identical semantics on
PostgreSQL and SQLite.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c15_nplus1_indexes"
down_revision: Union[str, Sequence[str], None] = "m3rge_task2_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (index_name, table, [columns]) — kept in one list so upgrade and
# downgrade can never drift apart.
HOT_FK_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_notifications_user_id", "notifications", ["user_id"]),
    ("ix_workspace_members_user_id", "workspace_members", ["user_id"]),
    ("ix_channel_members_user_id", "channel_members", ["user_id"]),
    ("ix_channels_workspace_id", "channels", ["workspace_id"]),
    ("ix_messages_channel_created", "messages", ["channel_id", "created_at"]),
    ("ix_messages_author_id", "messages", ["author_id"]),
    ("ix_messages_parent_id", "messages", ["parent_id"]),
    ("ix_projects_workspace_id", "projects", ["workspace_id"]),
    ("ix_tasks_project_id", "tasks", ["project_id"]),
    ("ix_tasks_assignee_id", "tasks", ["assignee_id"]),
    ("ix_pages_workspace_id", "pages", ["workspace_id"]),
    ("ix_pages_parent_id", "pages", ["parent_id"]),
    ("ix_files_workspace_id", "files", ["workspace_id"]),
    ("ix_files_uploader_id", "files", ["uploader_id"]),
    ("ix_events_workspace_id", "events", ["workspace_id"]),
    ("ix_task_comments_task_id", "task_comments", ["task_id"]),
]


def upgrade() -> None:
    for name, table, columns in HOT_FK_INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(HOT_FK_INDEXES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(name)
