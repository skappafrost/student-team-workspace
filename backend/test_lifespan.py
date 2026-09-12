"""T3-B04: lifespan startup replaces deprecated on_event."""

import warnings

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import app
from database import Base, engine


def test_lifespan_startup_creates_tables_without_deprecation_warning():
    """Entering 'with TestClient(app):' runs lifespan: tables ready, no on_event warning."""
    assert app.router.lifespan_context is not None
    # Start from no tables so only lifespan's create_all can materialize them.
    Base.metadata.drop_all(bind=engine)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            tables = set(inspect(engine).get_table_names())
            assert {"users", "workspaces"} <= tables
    assert not [
        w
        for w in caught
        if issubclass(w.category, DeprecationWarning) and "on_event" in str(w.message)
    ]
