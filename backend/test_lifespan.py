"""T3-B04: lifespan startup replaces the deprecated ``on_event`` hooks.

The same entry point used to build the app's own schema, which is how a broken or
never-run migration stayed invisible: whatever the chain failed to create,
``create_all`` quietly supplied. It no longer does. So this file pins the two
halves of the replacement — booting against a database nobody migrated succeeds,
creates no tables, answers 503 on ``/readyz``, and says the repair once on
``stw.schema``.
"""

import logging
import warnings
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import app
from database import Base, engine


@contextmanager
def lifespan_on_an_unmigrated_database():
    """Enter the real lifespan with zero tables: yields ``(client, warnings)``.

    A bare ``TestClient(app)`` — what ``conftest.client`` hands out, and what most
    of the suite uses — never runs lifespan, so the context manager below is the
    only thing in the package that exercises the startup block at all. The
    database is left empty on purpose: an unstamped, unmigrated file is exactly
    the state a deploy hits.
    """
    Base.metadata.drop_all(bind=engine)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with TestClient(app) as client:
            yield client, caught


def test_entering_the_lifespan_creates_no_tables():
    """The app serves while the schema is missing instead of materialising it."""
    assert app.router.lifespan_context is not None
    with lifespan_on_an_unmigrated_database() as (client, _):
        assert client.get("/health").status_code == 200
        tables = set(inspect(engine).get_table_names())
        assert {"users", "workspaces"}.isdisjoint(tables), f"startup created: {sorted(tables)}"


def test_unmigrated_database_holds_readyz_at_503():
    """The orchestrator's signal survives the deletion: 503, not a crash loop."""
    with lifespan_on_an_unmigrated_database() as (client, _):
        ready = client.get("/readyz")
    assert ready.status_code == 503
    body = ready.json()
    assert body["db"] is True, "the database answers; only the chain never ran"
    assert body["schema_current"] is False
    assert body["alembic_applied"] == []


def test_unmigrated_database_serves_no_write_through_the_app_engine():
    """A request that needs a table is refused, not handed one.

    This is the deletion seen from the inside: with the startup ``create_all``
    back, the boot below would materialise ``users`` and the register would answer
    201. ``raise_server_exceptions=False`` because the 500 is the result under
    test, not a crash to be surfaced.
    """
    Base.metadata.drop_all(bind=engine)
    with TestClient(app, raise_server_exceptions=False) as client:
        registered = client.post(
            "/auth/register",
            json={"email": "no-schema@example.com", "password": "long-enough-password"},
        )
    assert registered.status_code == 500, registered.text
    assert set(inspect(engine).get_table_names()) == set()


def test_unmigrated_database_warns_with_the_repair_named(caplog):
    """One ``stw.schema`` WARNING, naming both ways out of the state."""
    with caplog.at_level(logging.WARNING, logger="stw.schema"):
        with lifespan_on_an_unmigrated_database():
            pass
    messages = [r.getMessage() for r in caplog.records if r.name == "stw.schema"]
    assert len(messages) == 1, f"expected exactly one schema warning, got {messages}"
    assert "alembic upgrade head" in messages[0]
    assert "manage.py stamp" in messages[0], messages[0]


def test_startup_emits_no_on_event_deprecation_warning():
    """T3-B04's own claim: the replacement hook is used, so no Starlette warning."""
    with lifespan_on_an_unmigrated_database() as (_, caught):
        pass
    assert not [
        w
        for w in caught
        if issubclass(w.category, DeprecationWarning) and "on_event" in str(w.message)
    ]
