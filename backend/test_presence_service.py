"""Task LVT S5: presence service — HTTP set/list, idle→away TTL, WS fan-out.

Covers the S5 DoD: online/away/dnd/offline, heartbeat idle expiry, socket
revocation closing the WS (4401), and no cross-workspace leakage. HTTP paths
run through the DI-overridden session; the presence socket uses the module
session (same engine as conftest's db_session), so writes are visible to reads.
"""

import json

import pytest
from starlette.websockets import WebSocketDisconnect

import routers.presence as presence
from conftest import as_user, make_user
from dependencies import create_session


def _ws(client, owner="owner", slug="ws"):
    make_user(client._db, owner)
    as_user(client, owner)
    return client.post("/workspaces", json={"name": "WS", "slug": slug, "description": "x"}).json()


def _member(client, ws_id, user_id, role="member"):
    """Create user + real membership in ``ws_id``; return its session JWT."""
    make_user(client._db, user_id)
    import models

    m = models.WorkspaceMembership(workspace_id=ws_id, user_id=user_id, role=role)
    client._db.add(m)
    token = create_session(user_id, client._db)
    client._db.commit()
    return token


def _plain_token(client, user_id):
    """A user + valid session token with NO workspace membership."""
    make_user(client._db, user_id)
    token = create_session(user_id, client._db)
    client._db.commit()
    return token


# ---------------------------------------------------------------------------
# HTTP set / list
# ---------------------------------------------------------------------------

def test_set_and_list_presence(client):
    ws = _ws(client)
    as_user(client, "owner")
    r = client.post(
        f"/workspaces/{ws['id']}/presence/me",
        json={"status": "dnd", "status_message": "In a meeting"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dnd"
    assert r.json()["status_message"] == "In a meeting"

    listing = client.get(f"/workspaces/{ws['id']}/presence").json()
    mine = [p for p in listing if p["user_id"] == "owner"]
    assert mine and mine[0]["status"] == "dnd"


def test_invalid_status_rejected(client):
    ws = _ws(client)
    as_user(client, "owner")
    r = client.post(f"/workspaces/{ws['id']}/presence/me", json={"status": "sleeping"})
    assert r.status_code == 422


def test_anonymous_cannot_read_presence(client):
    ws = _ws(client)
    from conftest import clear_auth

    clear_auth(client)
    assert client.get(f"/workspaces/{ws['id']}/presence").status_code == 401


def test_non_member_cannot_read_presence(client):
    ws = _ws(client, owner="owner", slug="wsA")
    outsider = _plain_token(client, "outsider")
    r = client.get(
        f"/workspaces/{ws['id']}/presence", headers={"Authorization": f"Bearer {outsider}"}
    )
    assert r.status_code == 403


def test_guest_cannot_set_presence(client):
    ws = _ws(client)
    guest_tok = _member(client, ws["id"], "gast", role="guest")
    r = client.post(
        f"/workspaces/{ws['id']}/presence/me", json={"status": "online"}, headers={"Authorization": f"Bearer {guest_tok}"}
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Idle -> away TTL (pure derivation, no scheduler)
# ---------------------------------------------------------------------------

def test_idle_online_derives_away(client, monkeypatch):
    ws = _ws(client)
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/presence/me", json={"status": "online"})
    monkeypatch.setattr(presence, "AWAY_AFTER_SECONDS", -1.0)  # everything is "stale"
    assert client.get(f"/workspaces/{ws['id']}/presence").json()[0]["status"] == "away"


def test_dnd_not_demoted_by_idle(client, monkeypatch):
    ws = _ws(client)
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/presence/me", json={"status": "dnd"})
    monkeypatch.setattr(presence, "AWAY_AFTER_SECONDS", -1.0)
    assert client.get(f"/workspaces/{ws['id']}/presence").json()[0]["status"] == "dnd"


# ---------------------------------------------------------------------------
# WebSocket lifecycle: connect->online broadcast, disconnect->offline, revoke
# ---------------------------------------------------------------------------

def test_ws_connect_broadcasts_online(client):
    ws = _ws(client)
    viewer = _member(client, ws["id"], "viewer")
    actor = _member(client, ws["id"], "actor")

    with client.websocket_connect(
        f"/ws/workspaces/{ws['id']}/presence?session_token={viewer}"
    ) as vs:
        vs.receive_json()  # drain viewer's own online frame (broadcast includes self)
        with client.websocket_connect(
            f"/ws/workspaces/{ws['id']}/presence?session_token={actor}"
        ):
            frame = vs.receive_json()
            assert frame["type"] == "presence_update"
            assert frame["user_id"] == "actor"
            assert frame["status"] == "online"
        # actor disconnects -> offline reaches the still-open viewer
        offline = vs.receive_json()
        assert offline["user_id"] == "actor" and offline["status"] == "offline"


def test_ws_status_frame_updates_and_pings(client):
    ws = _ws(client)
    viewer = _member(client, ws["id"], "viewer")
    actor = _member(client, ws["id"], "actor")
    with client.websocket_connect(
        f"/ws/workspaces/{ws['id']}/presence?session_token={viewer}"
    ) as vs:
        vs.receive_json()  # viewer online (self)
        with client.websocket_connect(
            f"/ws/workspaces/{ws['id']}/presence?session_token={actor}"
        ) as aw:
            aw.receive_json()  # actor online (self)
            vs.receive_json()  # actor online reaches viewer
            aw.send_text(json.dumps({"type": "presence", "status": "dnd", "status_message": "heads down"}))
            self_dnd = aw.receive_json()  # presence broadcast includes the sender's room
            assert self_dnd["type"] == "presence_update" and self_dnd["status"] == "dnd"
            pong = aw.receive_json()
            assert pong["type"] == "pong"
            dnd = vs.receive_json()
            assert dnd["status"] == "dnd" and dnd["status_message"] == "heads down"


def test_ws_rejects_non_member(client):
    ws = _ws(client, owner="alice", slug="wA")
    outsider = _plain_token(client, "bob")  # member of nothing
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/workspaces/{ws['id']}/presence?session_token={outsider}"
        ) as w:
            w.receive_json()


def test_ws_rejects_revoked_session(client):
    ws = _ws(client)
    tok = _member(client, ws["id"], "revoker")
    as_user(client, "revoker")
    assert client.post("/auth/logout", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/ws/workspaces/{ws['id']}/presence?session_token={tok}"
        ) as w:
            w.receive_json()
    # handshake rejects a revoked jti before accept (WS_UNAUTHENTICATED 4401)
    assert exc.value.code == 4401
