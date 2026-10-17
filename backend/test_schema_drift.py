"""ARC-02 / ARC-03 — the schema the migrations build must be the schema the models describe.

Two contracts, both checked against a database that was actually created by
`alembic upgrade head`, not by `create_all`:

1. Every index the migration chain creates is also declared on the model. 21 of
   the 22 existed only in migrations, so every `create_all` database (the test
   databases `conftest.py` builds, and every developer file from before the
   server stopped creating its own schema) ran without them, and a future
   `--autogenerate` would have proposed dropping 21 of them. A drift test is the
   only thing that keeps the two lists from separating again.
2. A row can actually be inserted into `pages` on a migrated SQLite database.
   `add_kb_pages.py` used `server_default=sa.text("now()")` — the only such
   spelling in the chain — and SQLite has no `now()`, so the DEFAULT is accepted
   at DDL time and fails at INSERT time.

`ARC-04` joins them: three foreign keys the models declare (`messages.parent_id`
with the `ondelete="CASCADE"` that `routers/messages.py` documents as fact, and
`channels.created_by` / `events.created_by`) were added by `add_channel_fields.py`
and `add_calendar_event_fields.py` as plain `String` columns with no FK, so a
migration-built database accepts dangling ids that the model says are impossible.
`test_fk_enforcement.py` cannot see this: its fixture builds with
`Base.metadata.create_all`, which emits the model's FK — a test that validates a
schema nobody ships.

None of this is checkable from source text, which is why every test here builds a
real database with `alembic upgrade head`. The last test goes one step further and
binds the app's own engine to such a database, because a server that creates its
own schema at startup serves traffic no matter what the chain did — that is the
hole the deletion closed, and this is what keeps it closed.
"""

import os
import tempfile

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app import app
from conftest import TEST_DB_PATH, run_alembic
from database import set_db_url
from models import Base


def _migrate(url: str, to: str) -> None:
    """Run `alembic upgrade <to>` against `url`, restoring the environment after."""
    cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        run_alembic(command.upgrade, cfg, to)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _upgrade_head():
    """A fresh SQLite database at `alembic upgrade head`, with the app's FK pragma."""
    path = os.path.join(tempfile.mkdtemp(prefix="stw-drift-"), "drift.db")
    url = f"sqlite:///{path}"
    _migrate(url, "head")
    # `_make_engine` is what turns `PRAGMA foreign_keys` on; without it SQLite
    # would ignore every ondelete rule this file is about to exercise.
    from database import _make_engine

    return _make_engine(url)


@pytest.fixture(scope="module")
def migrated_engine():
    engine = _upgrade_head()
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def fresh_migrated_engine():
    """Per-test database: the behaviour tests write and delete rows."""
    engine = _upgrade_head()
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

    from conftest import make_user

    session = Session()
    try:
        make_user(session, "drift-user", email="drift-api@example.com")
    finally:
        session.close()

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


def test_models_and_migrations_declare_the_same_foreign_keys(migrated_engine):
    """Every model FK exists in the migrated schema, and nothing extra is only in it.

    Both directions: the missing one is the defect (ARC-04), the extra one would
    mean the migration chain enforces something the model does not describe.
    """
    inspector = inspect(migrated_engine)
    db_fk = {
        (table, column): fk["referred_table"]
        for table in inspector.get_table_names()
        for fk in inspector.get_foreign_keys(table)
        for column in fk["constrained_columns"]
    }
    model_fk = {
        (table.name, column.name): next(iter(column.foreign_keys)).target_fullname.split(".")[0]
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.foreign_keys
    }

    missing = sorted(f"{t}.{c} -> {r}" for (t, c), r in model_fk.items() if db_fk.get((t, c)) != r)
    extra = sorted(f"{t}.{c} -> {r}" for (t, c), r in db_fk.items() if (t, c) not in model_fk)
    assert not missing, f"model FKs absent from the migrated database: {missing}"
    assert not extra, f"FKs the migrated database has that the models do not: {extra}"


def test_deleting_a_parent_message_removes_its_replies_on_a_migrated_database(
    fresh_migrated_engine,
):
    """`messages.py` collects the subtree because it assumes DB cascade. Today the
    migrated schema has no FK, so the replies survive as orphans pointing at a
    deleted parent — the ghosts the docstring says cannot exist.
    """
    with fresh_migrated_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, display_name, is_active) "
                          "VALUES ('u1', 'fk@example.com', 'U', 1)"))
        conn.execute(text("INSERT INTO workspaces (id, name, slug) "
                          "VALUES ('w1', 'WS', 'fk-ws')"))
        conn.execute(text("INSERT INTO channels (id, workspace_id, name, type, created_by, "
                          "is_private) VALUES ('c1', 'w1', 'gen', 'general', 'u1', 0)"))
        conn.execute(text("INSERT INTO messages (id, channel_id, author_id, content, parent_id) "
                          "VALUES ('p1', 'c1', 'u1', 'parent', NULL), "
                          "('r1', 'c1', 'u1', 'reply', 'p1')"))
        conn.execute(text("DELETE FROM messages WHERE id = 'p1'"))
        orphaned = conn.execute(
            text("SELECT count(*) FROM messages WHERE parent_id = 'p1'")
        ).scalar()
    assert orphaned == 0, f"{orphaned} replies left pointing at a deleted message"


def test_bogus_channel_author_is_rejected_on_a_migrated_database(fresh_migrated_engine):
    """`channels.created_by` claimed to reference users but accepted any string."""
    with fresh_migrated_engine.begin() as conn:
        conn.execute(text("INSERT INTO workspaces (id, name, slug) "
                          "VALUES ('w1', 'WS', 'fk-ws2')"))
    with pytest.raises(IntegrityError):
        with fresh_migrated_engine.begin() as conn:
            conn.execute(text("INSERT INTO channels (id, workspace_id, name, type, created_by, "
                              "is_private) VALUES ('c1', 'w1', 'gen', 'general', "
                              "'nobody-at-all', 0)"))


@pytest.mark.parametrize("created_by", ["", "no-such-user"], ids=["placeholder", "dangling"])
def test_the_fk_revision_refuses_rows_it_cannot_link_instead_of_rewriting_them(
    tmp_path, created_by
):
    """`add_channel_fields.py` defaulted `created_by` to `''`, so real databases can
    hold channels the new FK cannot accept. The revision's contract is that it says
    so and leaves the data alone — reassigning an author or dropping a channel is a
    product decision, and silently making one in a migration is the failure mode.
    """
    from database import _make_engine

    url = "sqlite:///" + os.path.join(str(tmp_path), "guard.db")
    _migrate(url, "r2_pages_defaults")
    engine = _make_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, display_name, is_active) "
                          "VALUES ('u1', 'guard@example.com', 'G', 1)"))
        conn.execute(text("INSERT INTO workspaces (id, name, slug) "
                          "VALUES ('w1', 'WS', 'guard-ws')"))
        conn.execute(
            text("INSERT INTO channels (id, workspace_id, name, type, created_by, is_private) "
                 "VALUES ('c1', 'w1', 'gen', 'general', :cb, 0)"),
            {"cb": created_by},
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="will not reassign or delete"):
        _migrate(url, "head")

    engine = _make_engine(url)
    try:
        with engine.begin() as conn:
            left_alone = conn.execute(
                text("SELECT created_by FROM channels WHERE id = 'c1'")
            ).scalar()
            version = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        named = {fk["name"] for fk in inspect(engine).get_foreign_keys("channels")}
    finally:
        engine.dispose()
    assert left_alone == created_by, "the guard rewrote the row it refused to link"
    assert version == "r2_pages_defaults", "a failed revision still moved the schema stamp"
    assert "fk_channels_created_by" not in named, "the FK landed even though the guard raised"


def test_the_application_server_serves_a_chain_built_database(fresh_migrated_engine):
    """The gate this file exists for: the app's OWN engine, schema from migrations only.

    Every other test here either inspects the migrated engine directly or overrides
    `get_db` with its own session, so none proved what `database.SessionLocal` —
    the session a real request actually runs on — can do against a schema only
    `alembic upgrade head` built. Startup used to `create_all` over whatever the
    chain left behind, so a migration that failed outright still served traffic.
    `/readyz` answering 200 requires the `alembic_version` row no `create_all`
    writes; the register/read pair requires the request path to touch real tables.
    """
    url = str(fresh_migrated_engine.url)
    # Whatever the suite started with: the sqlite file locally, Postgres on CI.
    suite_url = os.environ.get("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
    set_db_url(url)
    try:
        with TestClient(app) as client:
            ready = client.get("/readyz")
            assert ready.status_code == 200, ready.text
            assert ready.json()["schema_current"] is True

            registered = client.post(
                "/auth/register",
                json={"email": "chain-built@example.com", "password": "long-enough-password"},
            )
            assert registered.status_code == 201, registered.text
            token = registered.json()["access_token"]

            me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert me.status_code == 200, me.text
            assert me.json()["email"] == "chain-built@example.com"
    finally:
        set_db_url(suite_url)
