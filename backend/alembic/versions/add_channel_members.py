"""add channel_members table for private channel membership

Revision ID: add_channel_members
Revises: 101f600f1926
Create Date: 2026-09-09 00:00:00.000000

Backfill policy (data preservation): existing private channels get every
current workspace member added as a member, so no one loses access that
had it before (previously the predicate granted access to any workspace
member). New private channels only contain the creator until members are
added via POST /channels/{id}/members.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_channel_members'
down_revision: Union[str, Sequence[str], None] = '101f600f1926'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create channel_members table and backfill existing private channels."""
    op.create_table(
        'channel_members',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('channel_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', 'user_id', name='uq_channel_members_channel_user'),
    )

    # Backfill: every workspace member of a private channel's workspace keeps access.
    import uuid

    bind = op.get_bind()
    channels = sa.table(
        'channels',
        sa.column('id', sa.String),
        sa.column('workspace_id', sa.String),
        sa.column('is_private', sa.Boolean),
    )
    workspace_members = sa.table(
        'workspace_members',
        sa.column('workspace_id', sa.String),
        sa.column('user_id', sa.String),
    )
    channel_members = sa.table(
        'channel_members',
        sa.column('id', sa.String),
        sa.column('channel_id', sa.String),
        sa.column('user_id', sa.String),
    )

    private_channels = bind.execute(
        sa.select(channels.c.id, channels.c.workspace_id).where(channels.c.is_private)
    ).fetchall()
    for channel_id, workspace_id in private_channels:
        user_ids = bind.execute(
            sa.select(workspace_members.c.user_id).where(
                workspace_members.c.workspace_id == workspace_id
            )
        ).scalars().all()
        for user_id in user_ids:
            bind.execute(
                channel_members.insert().values(
                    id=str(uuid.uuid4()),
                    channel_id=channel_id,
                    user_id=user_id,
                )
            )


def downgrade() -> None:
    """Drop channel_members table."""
    op.drop_table('channel_members')
