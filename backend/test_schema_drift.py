"""ARC-02 / ARC-03 — the schema the migrations build must be the schema the models describe.

Two contracts, both checked against a database that was actually created by
`alembic upgrade head`, not by `create_all`:

1. Every index the migration chain creates is also declared on the model. Today
   21 of the 22 indexes exist only in migrations, so every `create_all` database
   (every dev DB, both backend CI jobs, all 60 test databases) runs without them,
   and a future `--autogenerate` would propose dropping 21 of them. A drift test
   is the only thing that keeps the two lists from separating again.
2. A row can actually be inserted into `pages` on a migrated SQLite database.
   `add_kb_pages.py` used `server_default=sa.text("now()")` — the only such
   spelling in the chain — and SQLite has no `now()`, so the DEFAULT is accepted
   at DDL time and fails at INSERT time.

Neither is checkable from source text, which is why both build a real database.
"""

import os
import tempfile

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app import app
from conftest import run_alembic
from models import Base


@pytest.fixture(scope="module")
def migrated_engine():
    """An engine over a SQLite database produced by `alembic upgrade head`."""
    path = os.path.join(tempfile.mkdtemp(prefix="stw-drift-"), "drift.db")
    url = f"sqlite:///{path}"
    cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        run_alembic(command.upgrade, cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_models_declare_every_index_the_migrations_create(migrated_engine):
    """Undeclared indexes are invisible to `create_all` and to autogenerate."""
    inspector = inspect(migrated_engine)
    undeclared = []
    for table in sorted(inspector.get_table_names()):
        model = Base.metadata.tables.get(table)
        declared = {idx.name for idx in model.indexes} if model is not None else set()
        for idx in inspector.get_indexes(table):
            if idx["name"] not in declared:
                undeclared.append(f"{table}.{idx['name']}")
    assert undeclared == [], f"indexes that exist only in migrations: {undeclared}"


def test_pages_row_inserts_on_a_migration_built_database(migrated_engine):
    """`pages.created_at` must default without calling a function SQLite lacks."""
    with migrated_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, display_name, is_active) "
                 "VALUES ('u1', 'drift@example.com', 'Drift', 1)")
        )
        conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES ('w1', 'WS', 'drift-w1')")
        )
        conn.execute(
            text("INSERT INTO pages (id, workspace_id, slug, title, content, created_by) "
                 "VALUES ('p1', 'w1', 'drift-page', 'T', 'c', 'u1')")
        )
        row = conn.execute(
            text("SELECT created_at, updated_at FROM pages WHERE id = 'p1'")
        ).fetchone()
    assert row.created_at is not None, "server_default left created_at NULL"
    assert row.updated_at is not None, "server_default left updated_at NULL"


def test_page_can_be_created_through_the_api_on_a_migrated_database(
    migrated_engine, client
):
    """The contract a user hits, not just the DDL.

    A raw INSERT proves the DEFAULT is evaluable; this proves the whole path —
    route, schema, ORM, response model — works on a database built by
    `alembic upgrade head`, which is what CI's migration job produces.
    """
    from sqlalchemy.orm import sessionmaker

    from app import create_access_token
    from database import get_db

    Session = sessionmaker(bind=migrated_engine, autocommit=False, autoflush=False)

    def _override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    try:
        client.headers["Authorization"] = f"Bearer {create_access_token('drift-user')}"
        ws = client.post("/workspaces", json={"name": "Drift", "slug": "drift-ws"})
        assert ws.status_code == 201, ws.text
        resp = client.post(
            f"/workspaces/{ws.json()['id']}/pages",
            json={"slug": "first-page", "title": "First", "content": "# hi"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["created_at"], "the page came back without a created_at"
    finally:
        app.dependency_overrides.clear()
