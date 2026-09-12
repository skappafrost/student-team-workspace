"""Tests for the T3-B02 sliding-window rate limiter (backend/rate_limit.py).

Real-auth rule: login/register are public endpoints (no auth needed); the
upload/ai HTTP tests below authenticate with REAL JWTs via ``as_user`` --
never ``X-Test-User-*`` headers.

Isolation: the limiter store is process-global, so an autouse fixture resets
it before AND after every test in this module. Nothing here may pollute the
shared ``testclient``-IP / ``owner`` buckets used by the rest of the suite.
``RATELIMIT_ENABLED`` is toggled only via ``monkeypatch`` inside this file
(conftest.py untouched).
"""

import io
import uuid

import pytest

import rate_limit
from conftest import as_user, make_user


@pytest.fixture(autouse=True)
def _clean_limiter():
    rate_limit.reset()
    yield
    rate_limit.reset()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# HTTP: burst login -> 429 with Retry-After (IP bucket + email bucket)
# ---------------------------------------------------------------------------


def test_login_burst_returns_429_with_retry_after(client):
    # Part A -- 11 logins with DISTINCT nonexistent emails: the per-email
    # buckets stay at 1 hit each, so any 429 must come from the 10/min/IP
    # bucket. All allowed attempts read as 401 (bad credentials), never 500.
    statuses = []
    first_429 = None
    for i in range(11):
        resp = client.post(
            "/auth/login",
            json={"email": f"burst-a-{uuid.uuid4().hex[:8]}-{i}@example.com", "password": "wrong-password"},
        )
        statuses.append(resp.status_code)
        if resp.status_code == 429 and first_429 is None:
            first_429 = resp
    assert 401 in statuses
    assert 429 in statuses, f"expected a 429 in burst, got {statuses}"
    assert "retry-after" in first_429.headers
    assert int(first_429.headers["retry-after"]) >= 1

    # Part B -- same email 6 times: the 5/min/email bucket trips on the 6th
    # request even though the IP bucket still has room (state reset first).
    rate_limit.reset()
    email = f"burst-b-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert reg.status_code == 201, reg.text
    burst = [
        client.post("/auth/login", json={"email": email, "password": "wrong-password"})
        for _ in range(6)
    ]
    assert [r.status_code for r in burst] == [401] * 5 + [429]
    assert "retry-after" in burst[-1].headers
    assert int(burst[-1].headers["retry-after"]) >= 1


# ---------------------------------------------------------------------------
# HTTP: RATELIMIT_ENABLED=0 disables everything (monkeypatch, in-file only)
# ---------------------------------------------------------------------------


def test_ratelimit_disabled_allows_burst(client, monkeypatch):
    monkeypatch.setenv("RATELIMIT_ENABLED", "0")
    email = f"disabled-{uuid.uuid4().hex[:8]}@example.com"
    statuses = [
        client.post("/auth/login", json={"email": email, "password": "wrong-password"}).status_code
        for _ in range(12)
    ]
    assert 429 not in statuses
    assert set(statuses) == {401}


# ---------------------------------------------------------------------------
# HTTP: register 5/h per (IP, email) -> 6th same-email attempt is 429
# ---------------------------------------------------------------------------


def test_register_over_limit_returns_429(client):
    email = f"regcap-{uuid.uuid4().hex[:8]}@example.com"
    codes = [
        client.post("/auth/register", json={"email": email, "password": "password123"}).status_code
        for _ in range(6)
    ]
    assert codes[0] == 201
    assert codes[1:5] == [409] * 4
    assert codes[5] == 429


# ---------------------------------------------------------------------------
# HTTP: upload 20/h per user -> 21st upload is 429 with Retry-After
# ---------------------------------------------------------------------------


def test_upload_over_limit_returns_429(client, db_session):
    uid = _uid("rl-up")
    make_user(db_session, uid, email=f"{uid}@example.com")
    as_user(client, uid)
    ws = client.post(
        "/workspaces", json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}", "description": "x"}
    )
    assert ws.status_code == 201, ws.text
    ws_id = ws.json()["id"]

    last = None
    for i in range(21):
        last = client.post(
            f"/workspaces/{ws_id}/files",
            files={"file": (f"f{i}.pdf", io.BytesIO(b"x"), "application/pdf")},
        )
    assert last.status_code == 429, last.text
    assert "retry-after" in last.headers
    assert int(last.headers["retry-after"]) >= 1


# ---------------------------------------------------------------------------
# HTTP: ai 30/h per user -> 31st call is 429 (422s still count: dep runs first)
# ---------------------------------------------------------------------------


def test_ai_over_limit_returns_429(client, db_session):
    uid = _uid("rl-ai")
    make_user(db_session, uid, email=f"{uid}@example.com")
    as_user(client, uid)
    codes = [
        client.post("/ai/summarize", json={"kind": "unknown", "ref_id": "x"}).status_code
        for _ in range(31)
    ]
    assert codes[:30] == [422] * 30
    assert codes[30] == 429


# ---------------------------------------------------------------------------
# Unit: spec pins + sliding-window expiry for register/upload/ai buckets
# ---------------------------------------------------------------------------


def test_bucket_limits_match_spec():
    assert rate_limit.LOGIN_IP_LIMIT == (10, 60)
    assert rate_limit.LOGIN_EMAIL_LIMIT == (5, 60)
    assert rate_limit.REGISTER_LIMIT == (5, 3600)
    assert rate_limit.UPLOAD_LIMIT == (20, 3600)
    assert rate_limit.AI_LIMIT == (30, 3600)


def test_register_window_slides_and_isolates_keys():
    t0 = 1000.0
    for _ in range(5):
        allowed, retry = rate_limit.check("register", "1.2.3.4|a@example.com", 5, 3600, now=t0)
        assert (allowed, retry) == (True, 0.0)
    allowed, retry = rate_limit.check("register", "1.2.3.4|a@example.com", 5, 3600, now=t0)
    assert allowed is False
    assert retry == 3600.0
    # A different email on the same IP is unaffected.
    allowed, _ = rate_limit.check("register", "1.2.3.4|b@example.com", 5, 3600, now=t0)
    assert allowed is True
    # After the window slides past the oldest hit, the key is allowed again.
    allowed, _ = rate_limit.check("register", "1.2.3.4|a@example.com", 5, 3600, now=t0 + 3601.0)
    assert allowed is True


def test_upload_and_ai_user_buckets():
    t0 = 2000.0
    for _ in range(20):
        allowed, _ = rate_limit.check("upload", "user:x", 20, 3600, now=t0)
        assert allowed is True
    allowed, retry = rate_limit.check("upload", "user:x", 20, 3600, now=t0)
    assert allowed is False
    assert retry == 3600.0
    allowed, _ = rate_limit.check("upload", "user:y", 20, 3600, now=t0)
    assert allowed is True
    for _ in range(30):
        allowed, _ = rate_limit.check("ai", "user:x", 30, 3600, now=t0)
        assert allowed is True
    allowed, _ = rate_limit.check("ai", "user:x", 30, 3600, now=t0)
    assert allowed is False
