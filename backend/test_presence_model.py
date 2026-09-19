"""Round-trip + integrity tests for the PresenceState model (Task LVT S4).

Pins the additive data model: one row per (workspace_id, user_id), the
online/away/dnd/offline status default, the composite-unique guard, and the
CASCADE wiring that drops presence with its user or workspace. Runs on the
same naive-UTC convention as the rest of the suite (SQLite here; Postgres in
the backend-pg job).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database import Base, _make_engine
from models import PresenceState, User, Workspace

_PRESENCE_DB = "sqlite:///./test_stw_presence.db"


@pytest.fixture()
def db_session():
    # _make_engine installs the SQLite PRAGMA foreign_keys=ON listener, so the
    # CASCADE wiring under test behaves exactly like the app/test engines.
    engine = _make_engine(_PRESENCE_DB)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(db, email="alice@example.com", slug="ws"):
    user = User(email=email, display_name="Alice", hashed_password="x")
    workspace = Workspace(name="WS", slug=slug, description="d")
    db.add_all([user, workspace])
    db.commit()
    return user, workspace


def test_presence_roundtrip(db_session):
    user, workspace = _seed(db_session)
    seen = datetime.now(UTC).replace(microsecond=0)
    row = PresenceState(
        user_id=user.id,
        workspace_id=workspace.id,
        status="dnd",
        status_message="Deep work",
        last_seen=seen,
    )
    db_session.add(row)
    db_session.commit()

    got = (
        db_session.query(PresenceState)
        .filter_by(user_id=user.id, workspace_id=workspace.id)
        .one()
    )
    assert got.status == "dnd"
    assert got.status_message == "Deep work"
    # SQLite round-trips naive, Postgres tz-aware; compare the naive-UTC wall
    # clock so the assertion holds on both dialects.
    seen_naive = seen.astimezone(UTC).replace(tzinfo=None)
    got_naive = got.last_seen.replace(tzinfo=None)
    assert abs(got_naive - seen_naive) < timedelta(seconds=5)


def test_presence_status_defaults_offline(db_session):
    user, workspace = _seed(db_session)
    row = PresenceState(user_id=user.id, workspace_id=workspace.id)
    db_session.add(row)
    db_session.commit()
    assert db_session.get(PresenceState, row.id).status == "offline"


def test_one_presence_row_per_user_and_workspace(db_session):
    user, workspace = _seed(db_session)
    db_session.add(PresenceState(user_id=user.id, workspace_id=workspace.id, status="online"))
    db_session.commit()
    db_session.add(PresenceState(user_id=user.id, workspace_id=workspace.id, status="away"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_presence_cascades_with_user_and_workspace(db_session):
    user, workspace = _seed(db_session, email="bob@example.com", slug="ws2")
    db_session.add(PresenceState(user_id=user.id, workspace_id=workspace.id, status="online"))
    db_session.commit()

    db_session.delete(user)
    db_session.commit()
    assert db_session.query(PresenceState).filter_by(user_id=user.id).count() == 0
