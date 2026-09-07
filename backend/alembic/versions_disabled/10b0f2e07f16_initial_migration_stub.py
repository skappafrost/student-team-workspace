"""initial migration (stub for version stamp compatibility)

Revision ID: 10b0f2e07f16
Revises:
Create Date: 2026-08-26 11:15:42.054429

Reconstructed stub: the original source file was lost; the Postgres
database already has this revision applied. This module only exists so
alembic can resolve the recorded version id. It must never be run against
a database that has NOT already applied 10b0f2e07f16 (use schema_v1 instead).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "10b0f2e07f16"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    raise RuntimeError(
        "10b0f2e07f16 is a legacy stamp-only migration. The original initial "
        "migration was replaced by 9926de6687ec_schema_v1; databases created "
        "fresh should upgrade directly to 9926de6687ec."
    )


def downgrade() -> None:
    raise RuntimeError("10b0f2e07f16 is a legacy stamp-only migration.")
