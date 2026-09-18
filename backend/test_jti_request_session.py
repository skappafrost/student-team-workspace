"""Regression tests (TA1-3): jti revocation must check the REQUEST session.

``_is_jti_revoked`` used to open its own ``SessionLocal()`` — a second DB
connection per authenticated request, and one that can read a DIFFERENT
database than the request's ``get_db`` session (in tests: any override;
in prod: pool churn + a revocation check outside the request's
transaction). These tests pin the fix:

1. Injected-session tests: ``get_db`` is overridden to serve a database
   the module-level ``SessionLocal`` does NOT serve. Auth must still work
   — if the revocation check ever bypasses the injected session, the jti
   row is missing there ("missing = revoked") and every session token
   reads as dead (401).
2. Revocation semantics: a jti revoked by one request's session must 401
   the next request carrying that jti; sibling sessions stay valid.
3. The WebSocket auth path keeps honoring revocation (1008 close).
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from app import app, Base
from conftest import TEST_DB_PATH, make_user
from database import get_db, set_db_url
from dependencies import create_session

# The DB the get_db override serves (auth rows live here).
OVERRIDE_DB = "sqlite:///./test_stw_jti_req.db"
# The DB the module-level SessionLocal serves in the injected-session
# tests: same schema, ZERO rows. Any code path that opens its own
# SessionLocal finds no jti row there and treats the token as revoked.
GLOBAL_DB = "sqlite:///./test_stw_jti_global.db"


def _suite_url() -> str:
    """The URL the suite engine started with (Postgres on backend-pg CI)."""
    return os.environ.get("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")


def _mint(db, user_id: str) -> str:
    """Create the real User row + a revocable auth session; return its JWT."""
    user = make_user(db, user_id)
    token = create_session(user.id, db)
    db.commit()
    return token


def _seed_session_token(engine, user_id: str) -> str:
    """Seed user + session on a fresh session bound to ``engine``; return JWT."""
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = factory()
    try:
        token = _mint(s, user_id)
    finally:
        s.close()
    return token


# ---------------------------------------------------------------------------
# 1. Injected-session fixtures: get_db serves OVERRIDE_DB while the
#    module-level SessionLocal serves an EMPTY GLOBAL_DB.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def shared_db():
    engines = [
        create_engine(url, connect_args={"check_same_thread": False})
        for url in (OVERRIDE_DB, GLOBAL_DB)
    ]
    for e in engines:
        Base.metadata.drop_all(bind=e)
        Base.metadata.create_all(bind=e)
    # Module-level SessionLocal now serves the empty DB: code that opens
    # its own session sees no auth rows there.
    set_db_url(GLOBAL_DB)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engines[0])
    s = factory()
    try:
        yield s
    finally:
        s.close()
        set_db_url(_suite_url())
        for e in engines:
            Base.metadata.drop_all(bind=e)
            e.dispose()


@pytest.fixture(scope="function")
def client_shared(shared_db):
    app.dependency_overrides[get_db] = lambda: shared_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. Per-request-session fixtures: every request transacts on a FRESH
#    session bound to the same DB (mirrors production get_db), so a
#    revocation committed by request N must be visible to request N+1.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def per_request_engine():
    engine = create_engine(OVERRIDE_DB, connect_args={"check_same_thread": False})
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # The WebSocket path calls next(get_db()) directly (no DI override),
    # so the module-level SessionLocal must serve the same DB here.
    set_db_url(OVERRIDE_DB)
    yield engine
    set_db_url(_suite_url())
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def client_fresh(per_request_engine):
    factory = sessionmaker(autocommit=False, autoflush=False, bind=per_request_engine)

    def _fresh_session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _fresh_session
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. The revocation check must run on the injected get_db session
# ---------------------------------------------------------------------------

def test_jti_check_uses_injected_session_on_me(client_shared, shared_db):
    """Active jti lives only in the DB the get_db override serves.

    /auth/me decodes via the request session, so the call must succeed.
    A private SessionLocal() reads the empty global DB, misses the row
    ("missing = revoked") and returns 401 instead.
    """
    token = _mint(shared_db, "alice")

    r = client_shared.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    assert r.json()["id"] == "alice"


def test_jti_check_uses_injected_session_on_protected_route(client_shared, shared_db):
    """Same property through get_current_user on a protected endpoint."""
    token = _mint(shared_db, "alice")

    r = client_shared.post("/auth/logout-all", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    assert r.json()["revoked"] == 1


# ---------------------------------------------------------------------------
# 2. Revocation semantics across requests
# ---------------------------------------------------------------------------

def test_revoked_jti_401_on_next_request(client_fresh, per_request_engine):
    """Revoke a jti (logout), then an authenticated call with it must 401."""
    token = _seed_session_token(per_request_engine, "bob")
    headers = {"Authorization": f"Bearer {token}"}

    assert client_fresh.get("/auth/me", headers=headers).status_code == 200

    r = client_fresh.post("/auth/logout", headers=headers)
    assert r.status_code == 200, r.text

    r = client_fresh.get("/auth/me", headers=headers)
    assert r.status_code == 401, "revocation from the logout request must bind the next request"


def test_revocation_isolated_per_jti(client_fresh, per_request_engine):
    """Revoking one session must not kill a sibling session of another user."""
    t1 = _seed_session_token(per_request_engine, "bob")
    t2 = _seed_session_token(per_request_engine, "carol")
    h1 = {"Authorization": f"Bearer {t1}"}
    h2 = {"Authorization": f"Bearer {t2}"}

    assert client_fresh.post("/auth/logout", headers=h1).status_code == 200
    assert client_fresh.get("/auth/me", headers=h1).status_code == 401
    assert client_fresh.get("/auth/me", headers=h2).status_code == 200


# ---------------------------------------------------------------------------
# 3. WebSocket auth path keeps honoring revocation
# ---------------------------------------------------------------------------

def test_ws_rejects_revoked_jti(client_fresh, per_request_engine):
    """A revoked jti must fail WS auth (1008) before any join logic."""
    token = _seed_session_token(per_request_engine, "bob")
    assert client_fresh.post("/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    with pytest.raises(WebSocketDisconnect):
        with client_fresh.websocket_connect(f"/ws/channels/123?session_token={token}") as ws:
            ws.receive_text()
