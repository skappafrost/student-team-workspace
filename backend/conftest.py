"""Shared pytest fixtures and real-auth helpers for the STW backend suite.

T004: every test authenticates with a REAL JWT (``create_access_token(user.id)``)
instead of the legacy ``X-Test-User-*`` bypass headers. Identities are backed by
real ``User`` rows so membership/author lookups behave like production.

The bypass itself is gated behind ``STW_TEST_AUTH=1`` + ``ENVIRONMENT`` in
{test, dev} (see app._test_auth_bypass_enabled) and is exercised ONLY by
``test_auth_bypass_flag.py``. This file intentionally does NOT enable it.
"""

import os

import pytest
from fastapi.testclient import TestClient
from jose import JWTError
from sqlalchemy.orm import sessionmaker

# Use a file-based SQLite database for tests - it survives across connections.
# Honor a CI-provided DATABASE_URL (the backend-pg job points this at Postgres)
# so the same suite runs against both dialects; default stays SQLite.
TEST_DB_PATH = "test_stw.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")

# Pin the suite to test mode like CI does (ENVIRONMENT: test): app.lifespan's
# JWT-secret governance gate (TA1-2) refuses to boot with the default secret
# outside {test, dev}, so tests entering `with TestClient(app)` need this.
os.environ.setdefault("ENVIRONMENT", "test")

# Import the app AFTER pinning DATABASE_URL so its engine targets the test DB.
from app import app, create_access_token  # noqa: E402
from database import Base, engine, get_db  # noqa: E402
from models import User  # noqa: E402


def is_postgres() -> bool:
    """True when the suite is running against the Postgres backend-pg job.

    ``DateTime(timezone=True)`` round-trips tz-aware values on Postgres
    (timestamptz) and naive ones on SQLite, so a handful of assertions have to
    account for the engine. Importable from any test module.
    """
    return os.environ.get("DATABASE_URL", "").startswith(("postgres", "postgresql"))


# ---------------------------------------------------------------------------
# Real-auth helpers (importable from test modules: `from conftest import ...`)
# ---------------------------------------------------------------------------

def auth_headers(user_id: str) -> dict:
    """Return real Bearer Authorization headers for ``user_id``."""
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def make_user(db, user_id: str, email: str | None = None, display_name: str | None = None) -> User:
    """Create (or fetch) the real User row backing a JWT identity."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        user = User(
            id=user_id,
            email=email or f"{user_id}@example.com",
            display_name=display_name or user_id,
        )
        db.add(user)
        db.commit()
    return user


def drain_until_reply(session) -> list[dict]:
    """Frames already in flight, read up to a heartbeat acknowledgement.

    ``WebSocketTestSession.receive_json()`` has no timeout: a test that reads a
    fixed number of frames hangs forever when the server sends fewer, and a hung
    CI job reports nothing. Both sockets answer a plain-text heartbeat with a
    ``pong``, so the drain is bounded whichever way the assertion goes — a missing
    frame becomes a failure with the frames it did see.
    """
    session.send_text("ping")
    frames: list[dict] = []
    while True:
        frame = session.receive_json()
        if frame.get("type") == "pong":
            return frames
        frames.append(frame)


def as_user(client: TestClient, user_id: str) -> None:
    """Authenticate ``client`` as ``user_id`` with a real JWT."""
    client.headers["Authorization"] = auth_headers(user_id)["Authorization"]


def clear_auth(client: TestClient) -> None:
    """Remove the Authorization header so subsequent requests are anonymous."""
    client.headers.pop("Authorization", None)


# ---------------------------------------------------------------------------
# Database / client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function", autouse=True)
def _reset_rate_limits():
    """Rate-limit state is process-global; clear it per test so high-volume
    files (e.g. test_projects_api) don't bleed hits into each other and 429."""
    import rate_limit

    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture(scope="function")
def db_session():
    """Provide a fresh database session for each test, with tables recreated."""
    # Drop and recreate all tables to ensure a clean state.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        # Drop tables after test to keep the file small.
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Provide a TestClient with the test database session overridden.

    The client ensures a real ``User`` row exists for whatever JWT identity
    (Bearer header or session cookie) each request carries (T014: with FK
    enforcement ON, membership/author rows referencing a ghost user_id would
    500). Invalid tokens are left alone so 401-path tests keep working.
    """
    def _get_db_override():
        return db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield _EnsuringClient(app, _db=db_session)
    app.dependency_overrides.clear()


class _EnsuringClient(TestClient):
    """TestClient that materializes the JWT identity's User row pre-request."""

    def __init__(self, *args, _db=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._db = _db

    def request(self, method, url, **kwargs):
        if self._db is not None:
            token = None
            headers = kwargs.get("headers") or {}
            auth = headers.get("Authorization", "") or self.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1]
            if not token:
                cookies = kwargs.get("cookies") or {}
                token = cookies.get("session_token") or self.cookies.get("session_token")
            if token:
                try:
                    from app import _decode_token as _dec
                    payload = _dec(token, self._db)
                    uid = (payload or {}).get("sub")
                    if uid and self._db.get(User, uid) is None:
                        self._db.add(User(
                            id=uid,
                            email=f"{uid}@example.com",
                            display_name=uid,
                        ))
                        self._db.commit()
                except JWTError:
                    # Malformed/expired token: let the app itself answer 401.
                    # (Narrow on purpose: a blanket ``except Exception`` here
                    # previously masked an import/signature regression in the
                    # auth path and kept the suite falsely green.)
                    pass
        return super().request(method, url, **kwargs)


# ---------------------------------------------------------------------------
# T004 shared factory fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def user_factory(db_session):
    """Factory fixture: ``user_factory(user_id, email=None, display_name=None)`` -> User."""
    def _factory(user_id: str, email: str | None = None, display_name: str | None = None) -> User:
        return make_user(db_session, user_id, email=email, display_name=display_name)

    return _factory


@pytest.fixture(scope="function")
def workspace_factory(client, db_session):
    """Factory fixture: create a workspace with ``user_id`` as owner (real JWT)."""
    def _factory(user_id: str = "owner", name: str = "WS", slug: str = "ws") -> dict:
        make_user(db_session, user_id)
        as_user(client, user_id)
        resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _factory
