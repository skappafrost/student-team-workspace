"""Add page_versions table for wiki history (F09).

Revision ID: f9a01_page_versions
Revises: e8b41_auth_sessions
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f9a01_page_versions"
down_revision: str | Sequence[str] | None = "e8b41_auth_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "page_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "page_id",
            sa.String(36),
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "author_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_page_versions_page_version",
        "page_versions",
        ["page_id", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_page_versions_page_version", table_name="page_versions")
    op.drop_table("page_versions")
