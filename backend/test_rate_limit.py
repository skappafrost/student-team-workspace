"""Tests for the T3-B02 sliding-window rate limiter (backend/rate_limit.py).

T4-E5 fallback audit: every POST/PATCH/DELETE route without a specific
limiter shares DEFAULT_WRITE_LIMIT per (identity, route group) via
``DefaultWriteLimitMiddleware``; the four specifically-limited families
(login/register/upload/ai) skip the fallback (never double-counted).

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
import re
import uuid
from pathlib import Path

import pytest
from starlette.requests import Request

import rate_limit
from app import create_access_token
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


# ---------------------------------------------------------------------------
# T4-E5 audit: every mutating route in app.py is covered by exactly one
# limiter (a specific one, or the fallback). Static check -- runs without
# any HTTP traffic and fails loudly if a new route is added without wiring.
# ---------------------------------------------------------------------------

#: The four families with their own tighter buckets (must SKIP the fallback).
_SPECIFICALLY_LIMITED = {
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/ai/summarize"),
    ("POST", "/workspaces/{workspace_id}/files"),
}


def _app_mutating_routes() -> list[tuple[str, str]]:
    src = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
    return [
        (method.upper(), path)
        for method, path in re.findall(r'@app\.(post|patch|delete|put)\(\s*"([^"]+)"', src)
    ]


def test_audit_every_mutating_route_has_a_limiter():
    routes = _app_mutating_routes()
    assert len(routes) >= 39, f"route regex broke? only found {len(routes)}: {routes}"
    for method, path in routes:
        group = rate_limit._write_group(method, path)
        if (method, path) in _SPECIFICALLY_LIMITED:
            assert group is None, f"{method} {path}: specifically limited, must skip fallback"
        else:
            assert group is not None, f"{method} {path}: NO limiter covers this route"


# ---------------------------------------------------------------------------
# T4-E5 unit: fallback spec pin + group mapping + identity keying
# ---------------------------------------------------------------------------


def test_default_write_limit_matches_spec():
    assert rate_limit.DEFAULT_WRITE_LIMIT == (120, 60)


def test_write_group_mapping():
    cases = [
        # Specifically limited -> skipped (None).
        ("POST", "/auth/login", None),
        ("POST", "/auth/register", None),
        ("POST", "/ai/summarize", None),
        ("POST", "/workspaces/abc123/files", None),
        # Safe methods -> skipped even on write paths.
        ("GET", "/workspaces", None),
        ("GET", "/ai/search", None),
        ("HEAD", "/health", None),
        ("OPTIONS", "/workspaces", None),
        # Fallback groups (template paths as written in app.py + real paths).
        ("POST", "/auth/logout", "auth"),
        ("POST", "/workspaces", "workspaces"),
        ("PATCH", "/workspaces/{workspace_id}", "workspaces"),
        ("DELETE", "/workspaces/abc", "workspaces"),
        ("POST", "/workspaces/{workspace_id}/transfer-ownership", "workspaces"),
        ("POST", "/workspaces/{workspace_id}/invites", "invites"),
        ("POST", "/invites/accept", "invites"),
        ("PATCH", "/workspaces/{workspace_id}/invites/{invite_id}", "invites"),
        ("DELETE", "/workspaces/abc/invites/def", "invites"),
        ("PATCH", "/workspaces/{workspace_id}/members/{user_id}", "members"),
        ("DELETE", "/workspaces/abc/members/def", "members"),
        ("POST", "/workspaces/{workspace_id}/channels", "channels"),
        ("PATCH", "/channels/{channel_id}", "channels"),
        ("POST", "/channels/abc/members", "members"),
        ("DELETE", "/channels/abc/members/def", "members"),
        ("POST", "/channels/{channel_id}/messages", "messages"),
        ("PATCH", "/messages/{message_id}", "messages"),
        ("DELETE", "/messages/abc", "messages"),
        ("POST", "/workspaces/{workspace_id}/events", "events"),
        ("PATCH", "/events/{event_id}", "events"),
        ("DELETE", "/events/abc", "events"),
        ("POST", "/workspaces/{workspace_id}/projects", "projects"),
        ("PATCH", "/projects/{project_id}", "projects"),
        ("DELETE", "/projects/abc", "projects"),
        ("POST", "/projects/{project_id}/tasks", "tasks"),
        ("PATCH", "/tasks/{task_id}", "tasks"),
        ("DELETE", "/tasks/abc", "tasks"),
        ("POST", "/workspaces/{workspace_id}/pages", "pages"),
        ("PATCH", "/workspaces/{workspace_id}/pages/{page_id}", "pages"),
        ("DELETE", "/workspaces/abc/pages/def", "pages"),
        ("POST", "/notifications", "notifications"),
        ("PATCH", "/notifications/{notification_id}", "notifications"),
        ("DELETE", "/notifications/abc", "notifications"),
        ("PATCH", "/files/{file_id}", "files"),
        ("DELETE", "/files/abc", "files"),
        # Trailing slash tolerance.
        ("POST", "/workspaces/", "workspaces"),
        ("POST", "/auth/login/", None),
    ]
    for method, path, expected in cases:
        assert rate_limit._write_group(method, path) == expected, f"{method} {path}"


def _req(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})


def test_fallback_key_prefers_jwt_sub():
    token = create_access_token("rl-user-1")
    req = _req({"Authorization": f"Bearer {token}"})
    assert rate_limit._fallback_key(req) == "user:rl-user-1"


def test_fallback_key_uses_test_header_without_jwt():
    req = _req({"X-Test-User-Id": "legacy-tester"})
    assert rate_limit._fallback_key(req) == "testuser:legacy-tester"


def test_fallback_key_falls_back_to_ip():
    assert rate_limit._fallback_key(_req()) == "ip:unknown"


def test_fallback_disabled_flag_skips_counting(monkeypatch):
    monkeypatch.setenv("RATELIMIT_ENABLED", "0")
    monkeypatch.setattr(rate_limit, "DEFAULT_WRITE_LIMIT", (1, 60))
    for _ in range(5):
        allowed, _ = rate_limit.check("write", "user:x:workspaces", 1, 60)
        assert allowed is True


# ---------------------------------------------------------------------------
# T4-E5 HTTP: covered families skip the fallback (patched to (1,60) so any
# fallback counting would 429 the 2nd request immediately).
# ---------------------------------------------------------------------------


def test_covered_login_skips_fallback(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "DEFAULT_WRITE_LIMIT", (1, 60))
    rate_limit.reset()
    codes = [
        client.post(
            "/auth/login",
            json={"email": f"cov-login-{uuid.uuid4().hex[:8]}-{i}@example.com",
                    "password": "wrong-password"},
        ).status_code
        for i in range(2)
    ]
    assert codes == [401, 401]


def test_covered_register_skips_fallback(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "DEFAULT_WRITE_LIMIT", (1, 60))
    rate_limit.reset()
    email = f"cov-reg-{uuid.uuid4().hex[:8]}@example.com"
    first = client.post("/auth/register", json={"email": email, "password": "password123"})
    second = client.post(
        "/auth/register", json={"email": f"cov-reg2-{uuid.uuid4().hex[:8]}@example.com",
                                 "password": "password123"}
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text


def test_covered_upload_skips_fallback(client, db_session, monkeypatch):
    monkeypatch.setattr(rate_limit, "DEFAULT_WRITE_LIMIT", (1, 60))
    uid = _uid("rl-cov-up")
    make_user(db_session, uid, email=f"{uid}@example.com")
    as_user(client, uid)
    ws = client.post(
        "/workspaces", json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}", "description": "x"}
    )
    assert ws.status_code == 201, ws.text
    ws_id = ws.json()["id"]
    rate_limit.reset()
    codes = [
        client.post(
            f"/workspaces/{ws_id}/files",
            files={"file": (f"f{i}.pdf", io.BytesIO(b"x"), "application/pdf")},
        ).status_code
        for i in range(2)
    ]
    assert codes == [201, 201]


def test_covered_ai_skips_fallback(client, db_session, monkeypatch):
    monkeypatch.setattr(rate_limit, "DEFAULT_WRITE_LIMIT", (1, 60))
    uid = _uid("rl-cov-ai")
    make_user(db_session, uid, email=f"{uid}@example.com")
    as_user(client, uid)
    rate_limit.reset()
    codes = [
        client.post("/ai/summarize", json={"kind": "unknown", "ref_id": "x"}).status_code
        for _ in range(2)
    ]
    assert codes == [422, 422]


# ---------------------------------------------------------------------------
# T4-E5 HTTP: one fallback test per route group. Each patches the fallback
# to (2,60) (fast: 3 ops trip it), resets after setup, then asserts the 3rd
# op is 429 with Retry-After + write: detail while the first two pass the
# limiter. All auth via real JWT (make_user/as_user).
# ---------------------------------------------------------------------------


def _tiny_fallback(monkeypatch):
    """Patch the fallback to (2,60) and reset -- call AFTER test setup."""
    monkeypatch.setattr(rate_limit, "DEFAULT_WRITE_LIMIT", (2, 60))
    rate_limit.reset()


def _assert_fallback_trips(op):
    r1, r2, r3 = op(), op(), op()
    assert r1.status_code != 429, r1.text
    assert r2.status_code != 429, r2.text
    assert r3.status_code == 429, r3.text
    assert "retry-after" in r3.headers
    assert int(r3.headers["retry-after"]) >= 1
    assert "write:" in r3.json()["detail"]


def _mk_user_ws(client, db_session, prefix):
    """Real-JWT user + workspace they own; returns (uid, ws_id)."""
    uid = _uid(prefix)
    make_user(db_session, uid, email=f"{uid}@example.com")
    as_user(client, uid)
    ws = client.post(
        "/workspaces", json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}", "description": "x"}
    )
    assert ws.status_code == 201, ws.text
    return uid, ws.json()["id"]


def test_fallback_auth_logout(client, db_session, monkeypatch):
    uid = _uid("rl-fb-logout")
    make_user(db_session, uid, email=f"{uid}@example.com")
    as_user(client, uid)
    _tiny_fallback(monkeypatch)
    _assert_fallback_trips(lambda: client.post("/auth/logout"))


def test_fallback_workspace_create(client, db_session, monkeypatch):
    uid = _uid("rl-fb-ws")
    make_user(db_session, uid, email=f"{uid}@example.com")
    as_user(client, uid)
    _tiny_fallback(monkeypatch)
    _assert_fallback_trips(
        lambda: client.post(
            "/workspaces",
            json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}", "description": "x"},
        )
    )


def test_fallback_workspace_patch(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-wsp")
    _tiny_fallback(monkeypatch)
    i = iter(range(100))
    _assert_fallback_trips(
        lambda: client.patch(f"/workspaces/{ws_id}", json={"name": f"Renamed-{next(i)}"})
    )


def test_fallback_workspace_delete(client, db_session, monkeypatch):
    uid = _uid("rl-fb-wsd")
    make_user(db_session, uid, email=f"{uid}@example.com")
    as_user(client, uid)
    ids = []
    for _ in range(3):
        ws = client.post(
            "/workspaces",
            json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}", "description": "x"},
        )
        assert ws.status_code == 201, ws.text
        ids.append(ws.json()["id"])
    _tiny_fallback(monkeypatch)
    it = iter(ids)
    r1, r2, r3 = (client.delete(f"/workspaces/{next(it)}") for _ in range(3))
    assert [r1.status_code, r2.status_code] == [204, 204]
    assert r3.status_code == 429, r3.text
    assert "retry-after" in r3.headers


def test_fallback_invite_create(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-inv")
    _tiny_fallback(monkeypatch)
    _assert_fallback_trips(
        lambda: client.post(
            f"/workspaces/{ws_id}/invites",
            json={"email": f"inv-{uuid.uuid4().hex[:8]}@example.com", "role": "member"},
        )
    )


def test_fallback_invite_accept(client, db_session, monkeypatch):
    # One guest accepts invites to 3 DIFFERENT workspaces: same identity, so
    # all 3 hits land in one fallback bucket (201, 201, then 429).
    owner = _uid("rl-fb-acc")
    make_user(db_session, owner, email=f"{owner}@example.com")
    guest = _uid("rl-fb-guest")
    make_user(db_session, guest, email=f"{guest}@example.com")
    as_user(client, owner)
    tokens = []
    for _ in range(3):
        ws = client.post(
            "/workspaces",
            json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}", "description": "x"},
        )
        assert ws.status_code == 201, ws.text
        inv = client.post(
            f"/workspaces/{ws.json()['id']}/invites",
            json={"email": f"{guest}@example.com", "role": "member"},
        )
        assert inv.status_code == 201, inv.text
        tokens.append(inv.json()["token"])
    _tiny_fallback(monkeypatch)
    it = iter(tokens)
    as_user(client, guest)
    _assert_fallback_trips(lambda: client.post("/invites/accept", json={"token": next(it)}))


def _mk_member(client, db_session, prefix):
    """Owner workspace + a second user who joined as member; owner authed."""
    owner, ws_id = _mk_user_ws(client, db_session, prefix)
    as_user(client, owner)
    member = _uid(f"{prefix}-m")
    make_user(db_session, member, email=f"{member}@example.com")
    inv = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": f"{member}@example.com", "role": "member"},
    )
    assert inv.status_code == 201, inv.text
    as_user(client, member)
    acc = client.post("/invites/accept", json={"token": inv.json()["token"]})
    assert acc.status_code == 201, acc.text
    as_user(client, owner)
    return owner, member, ws_id


def test_fallback_member_patch(client, db_session, monkeypatch):
    owner, member, ws_id = _mk_member(client, db_session, "rl-fb-mem")
    as_user(client, owner)
    _tiny_fallback(monkeypatch)
    roles = iter(["admin", "member", "admin"])
    _assert_fallback_trips(
        lambda: client.patch(f"/workspaces/{ws_id}/members/{member}", json={"role": next(roles)})
    )


def test_fallback_member_delete(client, db_session, monkeypatch):
    owner, ws_id = _mk_user_ws(client, db_session, "rl-fb-memd")
    as_user(client, owner)
    doomed = []
    for _ in range(3):
        m = _uid("rl-fb-doom")
        make_user(db_session, m, email=f"{m}@example.com")
        inv = client.post(
            f"/workspaces/{ws_id}/invites", json={"email": f"{m}@example.com", "role": "member"}
        )
        assert inv.status_code == 201, inv.text
        as_user(client, m)
        acc = client.post("/invites/accept", json={"token": inv.json()["token"]})
        assert acc.status_code == 201, acc.text
        as_user(client, owner)
        doomed.append(m)
    _tiny_fallback(monkeypatch)
    it = iter(doomed)
    r1, r2, r3 = (client.delete(f"/workspaces/{ws_id}/members/{next(it)}") for _ in range(3))
    assert [r1.status_code, r2.status_code] == [204, 204]
    assert r3.status_code == 429, r3.text
    assert "retry-after" in r3.headers


def test_fallback_channel_create(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-ch")
    _tiny_fallback(monkeypatch)
    _assert_fallback_trips(
        lambda: client.post(
            f"/workspaces/{ws_id}/channels",
            json={"name": f"c-{uuid.uuid4().hex[:8]}", "type": "general"},
        )
    )


def _mk_channel(client, db_session, prefix):
    _, ws_id = _mk_user_ws(client, db_session, prefix)
    ch = client.post(
        f"/workspaces/{ws_id}/channels", json={"name": "general", "type": "general"}
    )
    assert ch.status_code == 201, ch.text
    return ws_id, ch.json()["id"]


def test_fallback_channel_patch(client, db_session, monkeypatch):
    _, ch_id = _mk_channel(client, db_session, "rl-fb-chp")
    _tiny_fallback(monkeypatch)
    i = iter(range(100))
    _assert_fallback_trips(
        lambda: client.patch(f"/channels/{ch_id}", json={"name": f"renamed-{next(i)}"})
    )


def test_fallback_channel_member_add(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-chm")
    ch = client.post(
        f"/workspaces/{ws_id}/channels", json={"name": "general", "type": "general"}
    )
    assert ch.status_code == 201, ch.text
    ch_id = ch.json()["id"]
    newcomers = []
    for _ in range(3):
        u = _uid("rl-fb-new")
        make_user(db_session, u, email=f"{u}@example.com")
        newcomers.append(u)
    _tiny_fallback(monkeypatch)
    it = iter(newcomers)
    _assert_fallback_trips(lambda: client.post(f"/channels/{ch_id}/members", json={"user_id": next(it)}))


def test_fallback_message_create(client, db_session, monkeypatch):
    _, ch_id = _mk_channel(client, db_session, "rl-fb-msg")
    _tiny_fallback(monkeypatch)
    i = iter(range(100))
    _assert_fallback_trips(
        lambda: client.post(f"/channels/{ch_id}/messages", json={"content": f"hello-{next(i)}"})
    )


def test_fallback_message_patch_delete(client, db_session, monkeypatch):
    _, ch_id = _mk_channel(client, db_session, "rl-fb-msgpd")
    msg = client.post(f"/channels/{ch_id}/messages", json={"content": "hello"})
    assert msg.status_code == 201, msg.text
    msg_id = msg.json()["id"]
    _tiny_fallback(monkeypatch)
    i = iter(range(100))
    _assert_fallback_trips(
        lambda: client.patch(f"/messages/{msg_id}", json={"content": f"edited-{next(i)}"})
    )
    rate_limit.reset()
    r1 = client.delete(f"/messages/{msg_id}")
    assert r1.status_code == 204, r1.text


def test_fallback_event_crud(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-ev")
    _tiny_fallback(monkeypatch)
    i = iter(range(100))

    def _create():
        n = next(i)
        return client.post(
            f"/workspaces/{ws_id}/events",
            json={
                "title": f"Event-{n}",
                "description": "desc",
                "start_at": "2026-08-28T09:00:00",
                "end_at": "2026-08-28T10:00:00",
                "all_day": False,
                "event_type": "meeting",
            },
        )

    r1, r2, r3 = _create(), _create(), _create()
    assert [r1.status_code, r2.status_code] == [201, 201]
    assert r3.status_code == 429, r3.text
    ev_id = r1.json()["id"]
    rate_limit.reset()
    assert client.patch(f"/events/{ev_id}", json={"title": "E2"}).status_code == 200
    assert client.delete(f"/events/{ev_id}").status_code == 204


def test_fallback_project_task_crud(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-proj")
    _tiny_fallback(monkeypatch)
    p1 = client.post(f"/workspaces/{ws_id}/projects", json={"name": "P1"})
    p2 = client.post(f"/workspaces/{ws_id}/projects", json={"name": "P2"})
    p3 = client.post(f"/workspaces/{ws_id}/projects", json={"name": "P3"})
    assert [p1.status_code, p2.status_code] == [201, 201]
    assert p3.status_code == 429, p3.text
    proj_id = p1.json()["id"]
    rate_limit.reset()
    t1 = client.post(f"/projects/{proj_id}/tasks", json={"title": "T1"})
    t2 = client.post(f"/projects/{proj_id}/tasks", json={"title": "T2"})
    t3 = client.post(f"/projects/{proj_id}/tasks", json={"title": "T3"})
    assert [t1.status_code, t2.status_code] == [201, 201]
    assert t3.status_code == 429, t3.text
    assert "write:" in t3.json()["detail"]
    rate_limit.reset()
    task_id = t1.json()["id"]
    assert client.patch(f"/tasks/{task_id}", json={"status": "doing"}).status_code == 200
    assert client.delete(f"/tasks/{task_id}").status_code == 204


def test_fallback_page_crud(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-page")
    _tiny_fallback(monkeypatch)

    def _create():
        slug = f"pg-{uuid.uuid4().hex[:8]}"
        return client.post(
            f"/workspaces/{ws_id}/pages",
            json={"title": "Doc", "slug": slug, "content": "# Hello"},
        )

    r1, r2, r3 = _create(), _create(), _create()
    assert [r1.status_code, r2.status_code] == [201, 201]
    assert r3.status_code == 429, r3.text
    page_id = r1.json()["id"]
    rate_limit.reset()
    assert client.patch(f"/workspaces/{ws_id}/pages/{page_id}", json={"title": "Doc2"}).status_code == 200
    assert client.delete(f"/workspaces/{ws_id}/pages/{page_id}").status_code == 204


def test_fallback_notification_crud(client, db_session, monkeypatch):
    uid, _ = _mk_user_ws(client, db_session, "rl-fb-notif")
    as_user(client, uid)
    target = _uid("rl-fb-target")
    make_user(db_session, target, email=f"{target}@example.com")
    _tiny_fallback(monkeypatch)
    i = iter(range(100))

    def _create():
        return client.post(
            "/notifications",
            json={
                "user_id": target,
                "type": "task-assigned",
                "title": f"Assigned-{next(i)}",
                "content": "body",
            },
        )

    r1, r2, r3 = _create(), _create(), _create()
    assert [r1.status_code, r2.status_code] == [201, 201]
    assert r3.status_code == 429, r3.text
    notif_id = r1.json()["id"]
    rate_limit.reset()
    as_user(client, target)
    assert client.patch(f"/notifications/{notif_id}", json={"read": True}).status_code == 200
    assert client.delete(f"/notifications/{notif_id}").status_code == 204


def _upload_file(client, ws_id, name):
    resp = client.post(
        f"/workspaces/{ws_id}/files",
        files={"file": (name, io.BytesIO(b"x"), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_fallback_file_patch(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-file")
    file_id = _upload_file(client, ws_id, "doc.pdf")
    _tiny_fallback(monkeypatch)
    i = iter(range(100))
    _assert_fallback_trips(
        lambda: client.patch(f"/files/{file_id}", json={"name": f"renamed-{next(i)}.pdf"})
    )


def test_fallback_file_delete(client, db_session, monkeypatch):
    _, ws_id = _mk_user_ws(client, db_session, "rl-fb-filed")
    ids = [_upload_file(client, ws_id, f"doc{i}.pdf") for i in range(3)]
    _tiny_fallback(monkeypatch)
    it = iter(ids)
    r1, r2, r3 = (client.delete(f"/files/{next(it)}") for _ in range(3))
    assert [r1.status_code, r2.status_code] == [204, 204]
    assert r3.status_code == 429, r3.text
    assert "retry-after" in r3.headers
