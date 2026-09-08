"""add task position

Revision ID: add_task_position
Revises: 9926de6687ec
Create Date: 2026-08-28 12:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_task_position"
down_revision: str | Sequence[str] | None = "9926de6687ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add position column to tasks table."""
    op.add_column("tasks", sa.Column("position", sa.Float(), nullable=False, server_default="0.0"))


def downgrade() -> None:
    """Remove position column from tasks table."""
    op.drop_column("tasks", "position")
