"""add calendar event fields

Revision ID: add_calendar_event_fields
Revises: add_task_position
Create Date: 2026-08-28 17:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_calendar_event_fields'
down_revision: Union[str, Sequence[str], None] = 'add_task_position'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add all_day, event_type, created_by, updated_at to events table."""
    op.add_column('events', sa.Column('all_day', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('events', sa.Column('event_type', sa.String(length=50), nullable=False, server_default='reminder'))
    op.add_column('events', sa.Column('created_by', sa.String(length=36), nullable=False, server_default=''))
    op.add_column('events', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False))


# SQLite doesn't support adding FK constraints via ALTER; rely on model-level
# foreign key enforcement. For PostgreSQL this would be created by a separate
# batch migration or via Base.metadata.create_all / autogenerate.


def downgrade() -> None:
    """Remove calendar event fields from events table."""
    op.drop_column('events', 'updated_at')
    op.drop_column('events', 'created_by')
    op.drop_column('events', 'event_type')
    op.drop_column('events', 'all_day')
