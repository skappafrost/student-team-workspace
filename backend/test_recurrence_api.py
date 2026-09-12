"""Tests for recurring events expansion (F08)."""

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app
from models import User


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_recurrence.db", echo=False)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def _get_db_override():
        return db_session

    from database import get_db

    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(client: TestClient, user_id: str, role: str = Role.OWNER.value):
    client.headers["X-Test-User-Id"] = user_id
    client.headers["X-Test-User-Role"] = role


@pytest.fixture(scope="function")
def ws_id(client, db_session):
    db_session.add(User(id="u1", email="u1@example.com", display_name="u1"))
    db_session.commit()
    as_user(client, "u1")
    return client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()["id"]


def _create(client, ws_id, title, start, recurrence="none", end=None):
    payload = {"title": title, "start_at": start.isoformat(), "recurrence": recurrence}
    if end:
        payload["end_at"] = end.isoformat()
    resp = client.post(f"/workspaces/{ws_id}/events", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_daily_event_expands_over_range(client, ws_id):
    base = datetime.datetime(2026, 9, 1, 9, 0, 0)
    ev = _create(client, ws_id, "standup", base, recurrence="daily")
    assert ev["recurrence"] == "daily"

    events = client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "2026-09-03T00:00:00", "end": "2026-09-06T23:59:59"},
    ).json()
    mine = [e for e in events if e["title"] == "standup"]
    assert len(mine) == 4  # Sep 3, 4, 5, 6
    assert [e["start_at"][:10] for e in mine] == [
        "2026-09-03",
        "2026-09-04",
        "2026-09-05",
        "2026-09-06",
    ]
    # Occurrences get distinct ids rooted at the base event.
    assert all(o["occurrence_id"].startswith(ev["id"] + "@") for o in mine)
    assert len({o["occurrence_id"] for o in mine}) == 4


def test_weekly_event_expands(client, ws_id):
    base = datetime.datetime(2026, 9, 1, 10, 0, 0)
    _create(client, ws_id, "weekly sync", base, recurrence="weekly")
    events = client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "2026-09-01T00:00:00", "end": "2026-09-30T23:59:59"},
    ).json()
    mine = [e for e in events if e["title"] == "weekly sync"]
    assert len(mine) == 5  # Sep 1, 8, 15, 22, 29


def test_monthly_event_expands_month_end_safe(client, ws_id):
    base = datetime.datetime(2026, 1, 31, 9, 0, 0)
    _create(client, ws_id, "monthly review", base, recurrence="monthly")
    events = client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "2026-01-01T00:00:00", "end": "2026-04-30T23:59:59"},
    ).json()
    mine = [e for e in events if e["title"] == "monthly review"]
    assert len(mine) == 4
    # Feb clamps to 28, Mar/Apr back to 31st would drift — we keep clamped day progression.
    assert mine[0]["start_at"][:10] == "2026-01-31"
    assert mine[1]["start_at"][:10] == "2026-02-28"


def test_duration_preserved_and_out_of_range_excluded(client, ws_id):
    base = datetime.datetime(2026, 9, 1, 9, 0, 0)
    end = datetime.datetime(2026, 9, 1, 10, 30, 0)
    _create(client, ws_id, "lab", base, recurrence="weekly", end=end)
    events = client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "2026-09-08T00:00:00", "end": "2026-09-08T23:59:59"},
    ).json()
    mine = [e for e in events if e["title"] == "lab"]
    assert len(mine) == 1
    occ = mine[0]
    assert occ["start_at"].endswith("09:00:00")
    assert occ["end_at"].endswith("10:30:00")


def test_no_range_returns_base_only(client, ws_id):
    base = datetime.datetime(2026, 9, 1, 9, 0, 0)
    _create(client, ws_id, "standup", base, recurrence="daily")
    events = client.get(f"/workspaces/{ws_id}/events").json()
    assert len(events) == 1
    assert events[0]["occurrence_id"] is None


def test_update_recurrence(client, ws_id):
    base = datetime.datetime(2026, 9, 1, 9, 0, 0)
    ev = _create(client, ws_id, "once", base)
    assert ev["recurrence"] == "none"
    updated = client.patch(f"/events/{ev['id']}", json={"recurrence": "weekly"}).json()
    assert updated["recurrence"] == "weekly"
    events = client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "2026-09-01T00:00:00", "end": "2026-09-30T23:59:59"},
    ).json()
    assert len([e for e in events if e["title"] == "once"]) == 5
