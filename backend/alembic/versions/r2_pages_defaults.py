"""ARC-03: give ``pages`` timestamp defaults a dialect-portable spelling.

``add_kb_pages.py`` declared ``server_default=sa.text("now()")`` — the only such
spelling in the whole chain. SQLite accepts arbitrary DDL, so the table is
created happily and every ``INSERT INTO pages`` then dies with
``OperationalError: unknown function: now()``. Measured end to end on a database
built by ``alembic upgrade head`` (see ``test_schema_drift.py``), not inferred
from the DDL.

``CURRENT_TIMESTAMP`` is what SQLAlchemy renders for ``func.now()`` on SQLite and
what the model already declares, so this revision brings the migrated schema in
line with the model instead of inventing a third spelling.

Revision ID: r2_pages_defaults
Revises: prs01_presence_state
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r2_pages_defaults"
down_revision: Union[str, Sequence[str], None] = "prs01_presence_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("created_at", "updated_at")


def upgrade() -> None:
    # Batch mode because SQLite cannot ALTER a column default in place; on
    # PostgreSQL the same call copies the table rather than rewriting rows.
    with op.batch_alter_table("pages") as batch_op:
        for column in _COLUMNS:
            batch_op.alter_column(
                column,
                existing_type=sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                existing_nullable=False,
            )


def downgrade() -> None:
    # Restores the previous DDL exactly, including the spelling that SQLite
    # cannot evaluate — downgrade is a fidelity operation, not a fix.
    with op.batch_alter_table("pages") as batch_op:
        for column in _COLUMNS:
            batch_op.alter_column(
                column,
                existing_type=sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                existing_nullable=False,
            )
