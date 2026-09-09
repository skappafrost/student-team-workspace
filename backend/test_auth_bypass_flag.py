"""T003: the X-Test-User-* header bypass must be active ONLY when the explicit
STW_TEST_AUTH=1 flag is set AND ENVIRONMENT is test/dev. Without the flag the
headers are ignored (401)."""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))


def _make_client(stw_test_auth: str | None, environment: str = "test"):
    os.environ["ENVIRONMENT"] = environment
    if stw_test_auth is None:
        os.environ.pop("STW_TEST_AUTH", None)
    else:
        os.environ["STW_TEST_AUTH"] = stw_test_auth
    import app as app_module
    importlib.reload(app_module)
    from database import Base, engine
    Base.metadata.create_all(bind=engine)
    from fastapi.testclient import TestClient
    return TestClient(app_module.app)


def test_bypass_headers_ignored_without_flag():
    client = _make_client(None)
    r = client.get("/workspaces", headers={"X-Test-User-Id": "attacker"})
    assert r.status_code == 401


def test_bypass_headers_ignored_in_prod_even_with_flag():
    client = _make_client("1", environment="prod")
    r = client.get("/workspaces", headers={"X-Test-User-Id": "attacker"})
    assert r.status_code == 401


def test_bypass_headers_work_in_test_with_flag():
    client = _make_client("1")
    r = client.get("/workspaces", headers={"X-Test-User-Id": "test-user"})
    assert r.status_code == 200


def test_bypass_headers_work_in_dev_with_flag():
    client = _make_client("1", environment="dev")
    r = client.get("/workspaces", headers={"X-Test-User-Id": "test-user"})
    assert r.status_code == 200
