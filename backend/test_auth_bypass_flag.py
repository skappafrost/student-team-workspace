"""T003/T004: the X-Test-User-* bypass is gated behind explicit test mode.

The bypass must be inert unless BOTH ``STW_TEST_AUTH=1`` AND ``ENVIRONMENT`` in
{"test", "dev"} are set at request time. This is the ONLY test module allowed to
toggle ``STW_TEST_AUTH``; every other test in the suite authenticates with real
JWTs (see conftest.py).
"""

import pytest
from fastapi.testclient import TestClient


def test_bypass_off_without_flag_returns_401(client, monkeypatch):
    """Default (CI-like) env: the bypass header is ignored -> 401."""
    monkeypatch.delenv("STW_TEST_AUTH", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    resp = client.get("/workspaces", headers={"X-Test-User-Id": "attacker"})
    assert resp.status_code == 401


def test_bypass_off_with_flag_but_wrong_env_returns_401(client, monkeypatch):
    """STW_TEST_AUTH=1 alone is not enough: ENVIRONMENT must be test/dev."""
    monkeypatch.setenv("STW_TEST_AUTH", "1")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    resp = client.get("/workspaces", headers={"X-Test-User-Id": "attacker"})
    assert resp.status_code == 401


def test_bypass_on_with_flag_and_test_env_returns_200(client, monkeypatch):
    """Bypass is active only with STW_TEST_AUTH=1 AND ENVIRONMENT=test."""
    monkeypatch.setenv("STW_TEST_AUTH", "1")
    monkeypatch.setenv("ENVIRONMENT", "test")
    resp = client.get("/workspaces", headers={"X-Test-User-Id": "attacker"})
    assert resp.status_code == 200
    assert resp.json() == []
