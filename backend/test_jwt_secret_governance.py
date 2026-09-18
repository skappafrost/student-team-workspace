"""TA1-2: the app refuses to start with the default JWT secret outside dev mode.

Governance gate follows the existing ``ENVIRONMENT`` convention (see
``_test_auth_bypass_enabled``): ``ENVIRONMENT`` in {"test", "dev"} is dev
mode; anything else — including unset — is production and MUST NOT boot while
``settings.jwt_secret_key`` is still the shipped default (or empty): that
value is public knowledge, so every token it signs is forgeable.
"""

import pytest
from fastapi.testclient import TestClient

from app import app
from config import JWT_SECRET_KEY_DEFAULT, settings
from database import Base, engine


def _fresh_schema():
    """Drop tables so only lifespan's create_all can materialize them."""
    Base.metadata.drop_all(bind=engine)


def test_default_secret_with_production_environment_refuses_startup(monkeypatch):
    """Default secret + ENVIRONMENT=production -> TestClient context raises."""
    _fresh_schema()
    monkeypatch.setattr(settings, "jwt_secret_key", JWT_SECRET_KEY_DEFAULT)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        with TestClient(app):
            pass


def test_default_secret_with_unset_environment_refuses_startup(monkeypatch):
    """Default secret + no ENVIRONMENT at all -> still refuses (unset = prod)."""
    _fresh_schema()
    monkeypatch.setattr(settings, "jwt_secret_key", JWT_SECRET_KEY_DEFAULT)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        with TestClient(app):
            pass


def test_empty_secret_with_production_environment_refuses_startup(monkeypatch):
    """Empty secret is as known as the default -> refuses."""
    _fresh_schema()
    monkeypatch.setattr(settings, "jwt_secret_key", "   ")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        with TestClient(app):
            pass


def test_default_secret_with_dev_environment_boots(monkeypatch):
    """Default secret + ENVIRONMENT=dev -> boots (dev mode is exempt)."""
    _fresh_schema()
    monkeypatch.setattr(settings, "jwt_secret_key", JWT_SECRET_KEY_DEFAULT)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_custom_secret_with_production_environment_boots(monkeypatch):
    """Strong secret + production -> boots normally (the happy hard path)."""
    _fresh_schema()
    monkeypatch.setattr(settings, "jwt_secret_key", "a-real-random-secret-48b")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
