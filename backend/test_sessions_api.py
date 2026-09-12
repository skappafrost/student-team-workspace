"""Tests for session revocation (S02)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, app


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_sessions.db", echo=False)
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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _restore_db_url():
    """_decode_token's revocation check reads the module-level SessionLocal;
    rebind it to the test DB per test, restore the configured URL after."""
    import database
    from config import settings

    original = settings.database_url
    database.set_db_url("sqlite:///./test_stw_sessions.db")
    yield
    database.set_db_url(original)


def _register(client, email, password="password123"):
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_logout_revokes_session(client, db_session):
    tokens = _register(client, "a@example.com")
    token = tokens["access_token"]

    # Token works before logout
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_logout_all_revokes_every_session(client):
    t1 = _register(client, "b@example.com")["access_token"]
    # second "device" = fresh login
    t2 = client.post(
        "/auth/login", json={"email": "b@example.com", "password": "password123"}
    ).json()["access_token"]

    resp = client.post("/auth/logout-all", headers={"Authorization": f"Bearer {t1}"})
    assert resp.status_code == 200
    assert resp.json()["revoked"] >= 2

    for token in (t1, t2):
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


def test_other_users_sessions_untouched(client):
    victim = _register(client, "c@example.com")["access_token"]
    actor = _register(client, "d@example.com")["access_token"]

    client.post("/auth/logout-all", headers={"Authorization": f"Bearer {actor}"})

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {victim}"})
    assert resp.status_code == 200
