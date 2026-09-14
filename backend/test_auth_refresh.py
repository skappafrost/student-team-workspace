"""TA1-1: POST /auth/refresh — rotation, replay/family invalidation, revocation.

All tests authenticate through the real endpoints (register/login) with real
JWTs. Refresh tokens come from TokenOut; negative paths that need a
deliberately broken token (expired, cross-user, unknown jti) are minted with
the real secret via jose / create_refresh_token so the endpoint's own
signature/expiry/claims checks are what rejects them.
"""

from datetime import UTC, datetime, timedelta

import models
from conftest import make_user
from dependencies import ALGORITHM, _get_secret, create_refresh_token
from jose import jwt as jose_jwt

PASSWORD = "super-secret-1"


def _register(client, email):
    resp = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client, email):
    resp = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _refresh(client, token):
    return client.post("/auth/refresh", json={"refresh_token": token})


# ---------------------------------------------------------------------------
# Happy path / full lifecycle (the spec's E2E scenario)
# ---------------------------------------------------------------------------


def test_full_lifecycle_login_refresh_replay_logout_all(client):
    """login -> refresh -> new pair works -> rotation chains -> logout-all
    kills everything -> old refresh replay fails.

    Note: replaying a rotated token triggers family invalidation (see
    test_replayed_refresh_token_kills_whole_family), so "new pair works" is
    asserted BEFORE the replay attempt — after a replay the whole family
    (including the newest pair) is dead by design.
    """
    _register(client, "ta11-life@example.com")  # row A: its own family (register)
    tokens = _login(client, "ta11-life@example.com")  # row B: its own family (login)

    r1 = _refresh(client, tokens["refresh_token"])
    assert r1.status_code == 200, r1.text
    rotated = r1.json()
    assert set(rotated) == {"access_token", "refresh_token", "token_type", "user"}
    assert rotated["token_type"] == "bearer"
    assert rotated["user"]["email"] == "ta11-life@example.com"
    # rotated pair is genuinely different from the login pair
    assert rotated["access_token"] != tokens["access_token"]
    assert rotated["refresh_token"] != tokens["refresh_token"]

    # new pair works: cookie was rotated onto the client
    me = client.get("/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "ta11-life@example.com"

    # rotation chains: the newest refresh token rotates again
    r2 = _refresh(client, rotated["refresh_token"])
    assert r2.status_code == 200, r2.text

    # logout-all kills everything: register row A + the live rotation row
    out = client.post("/auth/logout-all")
    assert out.status_code == 200, out.text
    assert out.json()["ok"] is True
    assert out.json()["revoked"] == 2  # register row + latest rotation row

    # newest refresh token is dead, and so is the newest access token
    assert _refresh(client, r2.json()["refresh_token"]).status_code == 401
    client.cookies.clear()
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r2.json()['access_token']}"})
    assert me.status_code == 401

    # old refresh token replay fails (revoked by rotation long ago)
    assert _refresh(client, tokens["refresh_token"]).status_code == 401


def test_register_issued_refresh_token_works(client):
    tokens = _register(client, "ta11-reg@example.com")
    r = _refresh(client, tokens["refresh_token"])
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "ta11-reg@example.com"


# ---------------------------------------------------------------------------
# Replay / family invalidation
# ---------------------------------------------------------------------------


def test_replayed_refresh_token_kills_whole_family(client):
    """Reusing a rotated refresh token revokes the entire rotation family —
    the newest pair from the same login dies with it (assumed theft)."""
    tokens = _register(client, "ta11-family@example.com")
    r1 = _refresh(client, tokens["refresh_token"])
    assert r1.status_code == 200
    rotated = r1.json()

    # replay the ORIGINAL (already-rotated) refresh token
    assert _refresh(client, tokens["refresh_token"]).status_code == 401

    # family kill: the rotated pair died too
    assert _refresh(client, rotated["refresh_token"]).status_code == 401
    client.cookies.clear()
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {rotated['access_token']}"})
    assert me.status_code == 401


# ---------------------------------------------------------------------------
# Revocation overlap with logout
# ---------------------------------------------------------------------------


def test_logout_revokes_refresh_token(client):
    """logout kills the shared session row, so the refresh token dies too
    (previously refresh tokens were stateless and survived logout)."""
    tokens = _register(client, "ta11-logout@example.com")
    # logout reads the session cookie set by register
    out = client.post("/auth/logout")
    assert out.status_code == 200
    assert _refresh(client, tokens["refresh_token"]).status_code == 401


def test_logout_all_after_rotation_kills_newest_pair(client):
    tokens = _register(client, "ta11-logoutall@example.com")
    r1 = _refresh(client, tokens["refresh_token"])
    assert r1.status_code == 200
    rotated = r1.json()
    out = client.post("/auth/logout-all")
    assert out.status_code == 200
    assert _refresh(client, rotated["refresh_token"]).status_code == 401


# ---------------------------------------------------------------------------
# Negative paths
# ---------------------------------------------------------------------------


def test_expired_refresh_token_rejected(client, db_session):
    tokens = _register(client, "ta11-expired@example.com")
    row = (
        db_session.query(models.AuthSession)
        .filter(models.AuthSession.user_id == tokens["user"]["id"])
        .first()
    )
    assert row is not None
    expired = jose_jwt.encode(
        {
            "sub": tokens["user"]["id"],
            "exp": datetime.now(UTC) - timedelta(minutes=1),
            "type": "refresh",
            "jti": row.jti,
        },
        _get_secret(),
        algorithm=ALGORITHM,
    )
    resp = _refresh(client, expired)
    assert resp.status_code == 401, resp.text
    # the live refresh token still works — expiry did not kill the family
    live = _refresh(client, tokens["refresh_token"])
    assert live.status_code == 200


def test_cross_user_refresh_token_rejected(client, db_session):
    """A correctly-signed token whose sub does not match the session row's
    user is rejected."""
    tokens = _register(client, "ta11-attacker@example.com")
    row = (
        db_session.query(models.AuthSession)
        .filter(models.AuthSession.user_id == tokens["user"]["id"])
        .first()
    )
    assert row is not None
    make_user(db_session, "ta11-victim-user")
    forged = create_refresh_token("ta11-victim-user", jti=row.jti)
    resp = _refresh(client, forged)
    assert resp.status_code == 401, resp.text


def test_unknown_jti_rejected(client):
    """Correctly-signed refresh token with a jti that has no session row."""
    tokens = _register(client, "ta11-unknown@example.com")
    forged = create_refresh_token(tokens["user"]["id"], jti="00000000-no-such-row")
    resp = _refresh(client, forged)
    assert resp.status_code == 401, resp.text


def test_malformed_refresh_token_rejected(client):
    _register(client, "ta11-malformed@example.com")
    assert _refresh(client, "not-a-jwt").status_code == 401
    # empty / missing field is a request-shape error (422), like login/register
    assert _refresh(client, "").status_code == 422
    resp = client.post("/auth/refresh", json={})
    assert resp.status_code == 422


def test_access_token_rejected_as_refresh_token(client):
    tokens = _register(client, "ta11-acc-as-ref@example.com")
    resp = _refresh(client, tokens["access_token"])
    assert resp.status_code == 401, resp.text


def test_refresh_token_rejected_as_access_token(client):
    """Regression guard: refresh tokens carry the session jti now, but the
    type claim must keep them out of the access-token path (incl. /auth/me)."""
    tokens = _register(client, "ta11-ref-as-acc@example.com")
    client.cookies.clear()
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert me.status_code == 401
