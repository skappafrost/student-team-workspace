"""ARC-04: give the three authorship/threads columns the FK the model declares.

``add_channel_fields.py`` and ``add_calendar_event_fields.py`` added
``channels.created_by``, ``events.created_by`` and ``messages.parent_id`` as plain
``String`` columns. The models declare all three as ``ForeignKey(...)`` — and
``routers/messages.py`` builds its subtree collection on the claim that
``messages.parent_id`` is ``ondelete="CASCADE"``, a claim that was only ever true
of a ``create_all`` database (which is what ``test_fk_enforcement.py`` builds, so
the suite stayed green while the shipped schema accepted dangling replies to a
deleted message).

Order matters and is deliberate: the data check runs BEFORE any DDL, because
``add_channel_fields.py`` gave ``created_by`` ``server_default=""`` NOT NULL, so
databases written before the column had an author carry empty strings that would
otherwise blow up the ALTER with a bare FK error. Refusing with an explanation is
chosen over rewriting rows: pointing an authorless channel at some user, or
deleting it, are both product decisions this migration must not make silently.

Revision ID: r3_authorship_fks
Revises: r2_pages_defaults
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r3_authorship_fks"
down_revision: Union[str, Sequence[str], None] = "r2_pages_defaults"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, referenced table, ondelete) — mirrors the model definitions.
FOREIGN_KEYS: list[tuple[str, str, str, str]] = [
    ("channels", "created_by", "users", "CASCADE"),
    ("events", "created_by", "users", "CASCADE"),
    ("messages", "parent_id", "messages", "CASCADE"),
]


def _assert_rows_are_linkable(table: str, column: str, ref_table: str) -> None:
    """Fail with instructions rather than a raw FK error, or worse, a silent fix."""
    bind = op.get_bind()
    placeholder = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL AND {column} = ''"  # noqa: S608
        )
    ).scalar()
    dangling = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {table} t LEFT JOIN {ref_table} r ON r.id = t.{column} "  # noqa: S608
            f"WHERE t.{column} IS NOT NULL AND t.{column} <> '' AND r.id IS NULL"
        )
    ).scalar()
    if not (placeholder or dangling):
        return
    raise RuntimeError(
        f"cannot add the foreign key {table}.{column} -> {ref_table}.id: "
        f"{placeholder} row(s) hold the '' placeholder that add_channel_fields.py "
        f"set as the column default, and {dangling} row(s) point at a {ref_table} "
        "that is not there. This revision will not reassign or delete them — that is "
        "a data decision. Give each row a real author (or remove the rows deliberately) "
        "and re-run `alembic upgrade head`."
    )


def upgrade() -> None:
    for table, column, ref_table, _ondelete in FOREIGN_KEYS:
        _assert_rows_are_linkable(table, column, ref_table)

    for table, column, ref_table, ondelete in FOREIGN_KEYS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(
                f"fk_{table}_{column}",
                ref_table,
                [column],
                ["id"],
                ondelete=ondelete,
            )


def downgrade() -> None:
    for table, column, _ref_table, _ondelete in reversed(FOREIGN_KEYS):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_{column}", type_="foreignkey")
