"""add presence_state table (Task LVT Phase 2 — realtime presence)

Per-user, per-workspace live presence: one row per (workspace_id, user_id)
member holding a status (online/away/dnd/offline), an optional status message,
and a naive-UTC last_seen that drives the idle→away/offline TTL. Additive only;
no backfill (a member with no row reads as offline).

``status`` is an un-constrained String(50) (validated in the service layer, like
the ``role`` columns), and the composite (workspace_id, status) index backs the
"who's online in this workspace" list query.

Revision ID: prs01_presence_state
Revises: m3rge_ta1_ta5_heads
Create Date: 2026-09-19 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "prs01_presence_state"
down_revision: Union[str, Sequence[str], None] = "m3rge_ta1_ta5_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "presence_state",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'offline'"), nullable=False),
        sa.Column("status_message", sa.String(length=255), nullable=True),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name="uq_presence_state_workspace_user"
        ),
    )
    op.create_index(
        "ix_presence_state_workspace_status", "presence_state", ["workspace_id", "status"]
    )


def downgrade() -> None:
    with op.batch_alter_table("presence_state") as batch_op:
        batch_op.drop_index("ix_presence_state_workspace_status")
    op.drop_table("presence_state")
