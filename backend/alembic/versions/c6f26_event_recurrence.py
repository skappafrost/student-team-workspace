"""add recurrence column to events (F08)

Revision ID: c6f26_event_recurrence
Revises: b5e15_channel_members
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6f26_event_recurrence"
down_revision: str | Sequence[str] | None = "b5e15_channel_members"
branch_labels = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("recurrence", sa.String(length=20), nullable=False, server_default="none"),
    )


def downgrade() -> None:
    op.drop_column("events", "recurrence")
