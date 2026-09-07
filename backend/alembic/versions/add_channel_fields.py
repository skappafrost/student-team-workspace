"""add channel created_by and type fields

Revision ID: add_channel_fields
Revises: add_calendar_event_fields
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_channel_fields'
down_revision: Union[str, Sequence[str], None] = 'add_calendar_event_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add type and created_by columns to channels; parent_id to messages."""
    op.add_column('channels', sa.Column('type', sa.String(length=50), nullable=False, server_default='general'))
    op.add_column('channels', sa.Column('created_by', sa.String(length=36), nullable=False, server_default=''))
    op.add_column('messages', sa.Column('parent_id', sa.String(length=36), nullable=True))


def downgrade() -> None:
    """Remove channel type/created_by and message parent_id."""
    op.drop_column('messages', 'parent_id')
    op.drop_column('channels', 'created_by')
    op.drop_column('channels', 'type')
