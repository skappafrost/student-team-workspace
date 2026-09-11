"""add channel_members table (DMs)

Revision ID: b5e15_channel_members
Revises: a4f04_message_reactions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e15_channel_members"
down_revision: str | Sequence[str] | None = "a4f04_message_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(36),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "user_id", name="uq_channel_user"),
    )
    op.create_index("ix_channel_members_channel_id", "channel_members", ["channel_id"])
    op.create_index("ix_channel_members_user_id", "channel_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_members_user_id", table_name="channel_members")
    op.drop_index("ix_channel_members_channel_id", table_name="channel_members")
    op.drop_table("channel_members")
