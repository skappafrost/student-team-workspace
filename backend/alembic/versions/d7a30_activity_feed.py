"""add activities table + notification link (R03)

Revision ID: d7a30_activity_feed
Revises: c6f26_event_recurrence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a30_activity_feed"
down_revision: str | Sequence[str] | None = "c6f26_event_recurrence"
branch_labels = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("link", sa.String(length=500), nullable=True))
    op.create_table(
        "activities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(length=36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("verb", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("target_label", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_activities_workspace_created", "activities", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_activities_workspace_created", table_name="activities")
    op.drop_table("activities")
    op.drop_column("notifications", "link")
