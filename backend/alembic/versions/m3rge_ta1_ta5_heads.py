"""Merge heads: TA1-1 refresh rotation + TA5-1 N+1 indexes.

PR #148 forked the Alembic timeline: ``a1f1_refresh_rotation`` (TA1-1) and
``a7c15_nplus1_indexes`` (TA5-1) both branched off ``m3rge_task2_heads`` and
neither was re-parented, leaving two declared heads and a
``MultipleHeadsError`` on ``alembic upgrade head`` (which wedges /readyz at
503 and breaks db-status). This empty merge re-joins them into a single head
without touching schema.

Revision ID: m3rge_ta1_ta5_heads
Revises: a1f1_refresh_rotation, a7c15_nplus1_indexes
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "m3rge_ta1_ta5_heads"
down_revision: Union[str, Sequence[str], None] = ("a1f1_refresh_rotation", "a7c15_nplus1_indexes")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
