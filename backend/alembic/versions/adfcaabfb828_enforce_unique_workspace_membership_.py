"""enforce unique workspace membership (workspace_id, user_id)

Revision ID: adfcaabfb828
Revises: 101f600f1926
Create Date: 2026-09-09 19:42:50.596523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'adfcaabfb828'
down_revision: Union[str, Sequence[str], None] = 'add_channel_members'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Dedupe existing duplicate memberships, then add a unique constraint.

    Collapse policy for pre-existing duplicates (documented choice, matches
    ROLE_HIERARCHY in app.py): keep the row with the most privileged role
    (owner > admin > member > guest); break ties by earliest joined_at. All
    other rows for the same (workspace_id, user_id) pair are deleted first so
    the constraint can be created on dirty databases (e.g. stw.db or
    test_stw*.db that already contain dup rows).
    """
    op.execute(
        """
        DELETE FROM workspace_members
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY workspace_id, user_id
                           ORDER BY CASE role
                               WHEN 'owner' THEN 4
                               WHEN 'admin' THEN 3
                               WHEN 'member' THEN 2
                               ELSE 1
                           END DESC,
                           joined_at ASC
                       ) AS rn
                FROM workspace_members
            ) ranked
            WHERE rn = 1
        )
        """
    )
    with op.batch_alter_table("workspace_members") as batch_op:
        batch_op.create_unique_constraint(
            "uq_workspace_members_workspace_user", ["workspace_id", "user_id"]
        )


def downgrade() -> None:
    """Drop the unique constraint."""
    with op.batch_alter_table("workspace_members") as batch_op:
        batch_op.drop_constraint("uq_workspace_members_workspace_user", type_="unique")
