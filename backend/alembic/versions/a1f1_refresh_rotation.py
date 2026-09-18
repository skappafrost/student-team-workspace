"""auth_sessions: rotation family + single-use flag (TA1-1 refresh rotation)

Revision ID: a1f1_refresh_rotation
Revises: m3rge_task2_heads

Adds two nullable/defaulted columns to auth_sessions:
  - family_id: chains rotation successor rows back to the original login
    session so a replayed refresh token can revoke the whole lineage.
  - rotated: marks rows already rotated into a successor (single-use
    refresh tokens; distinguishes "revoked by rotation" from "revoked by
    logout" for reuse detection).
No data backfill needed: existing rows are pre-rotation rows that were
never rotated (rotated defaults to false) and have no family (null).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f1_refresh_rotation"
down_revision: str | Sequence[str] | None = "m3rge_task2_heads"
branch_labels = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("family_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column(
            "rotated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Family lookups happen on every replayed refresh; index the lineage.
    op.create_index("ix_auth_sessions_family", "auth_sessions", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_family", table_name="auth_sessions")
    op.drop_column("auth_sessions", "rotated")
    op.drop_column("auth_sessions", "family_id")
