"""Task LVT S5: presence service — HTTP set/list, idle→away TTL, WS fan-out.

Covers the S5 DoD: online/away/dnd/offline, heartbeat idle expiry, socket
revocation closing the WS (4401), and no cross-workspace leakage. HTTP paths
run through the DI-overridden session; the presence socket uses the module
session (same engine as conftest's db_session), so writes are visible to reads.
"""

import json
import time

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


# ---------------------------------------------------------------------------
# Frame contract: only an explicit presence frame may change a status
# ---------------------------------------------------------------------------


def _collect(session, *frames) -> list[dict]:
    """Send ``frames``, then read everything the server answers.

    ``receive_json()`` has no timeout, so a test that reads a fixed number of
    frames hangs forever when the server answers with fewer — which is how the
    malformed-JSON case behaves today. The plain-text heartbeat is the barrier:
    it is answered under the old contract and the new one alike, so the drain
    terminates either way and a missing reply becomes an assertion instead of a
    stuck CI job.
    """
    for frame in frames:
        session.send_text(frame)
    session.send_text("ping")
    seen: list[dict] = []
    while True:
        frame = session.receive_json()
        if frame.get("type") == "pong":
            return seen
        seen.append(frame)


def _terminated(session) -> bool:
    """True when the server closed the socket, False while it keeps answering."""
    while True:
        try:
            frame = session.receive_json()
        except WebSocketDisconnect:
            return True
        if frame.get("type") in ("pong", "presence_error"):
            return False


def test_heartbeat_preserves_a_deliberate_dnd(client):
    """The documented keepalive must not undo the status the user picked.

    The receive loop initialised ``status = "online"`` *before* looking at the
    payload, so every frame that was not a well-formed presence frame — a bare
    ``ping``, a ``{"type":"ping"}``, a typo in a status — wrote ``online``.
    """
    ws = _ws(client)
    tok = _member(client, ws["id"], "keeper")
    with client.websocket_connect(_presence_url(ws["id"], tok)) as w:
        assert w.receive_json()["type"] == "presence_update"  # connect -> online
        as_user(client, "keeper")
        assert client.post(
            f"/workspaces/{ws['id']}/presence/me", json={"status": "dnd"}
        ).status_code == 200
        _collect(w)
        assert _status_of(client, ws["id"], tok, "keeper") == "dnd"


def test_heartbeat_broadcasts_nothing(client):
    """A keepalive that re-broadcast puts a frame on every peer's socket for a
    status that did not change."""
    ws = _ws(client)
    tok = _member(client, ws["id"], "ticker")
    viewer = _member(client, ws["id"], "watcher")
    with client.websocket_connect(_presence_url(ws["id"], viewer)) as vs, client.websocket_connect(
        _presence_url(ws["id"], tok)
    ) as w:
        _collect(vs)
        _collect(w)  # drains the join broadcasts for both sockets
        about_me = [f for f in _collect(w) if f.get("user_id") == "ticker"]
        assert about_me == [], f"a heartbeat was broadcast to peers: {about_me}"


def test_heartbeat_keeps_an_idle_tab_online(client, monkeypatch):
    """The other half of the rule: the keepalive has to keep *something* alive.

    ``effective_status`` derives ``away`` from a stale ``last_seen`` on a stored
    ``online`` row, so a heartbeat that wrote nothing at all would grey out
    every dot five minutes after the tab opened, socket alive or not. This
    passes before the fix too — deliberately: it is the control that stops the
    fix from being "make the heartbeat a no-op".
    """
    monkeypatch.setattr(presence, "AWAY_AFTER_SECONDS", 0.2)
    ws = _ws(client)
    tok = _member(client, ws["id"], "idler")
    with client.websocket_connect(_presence_url(ws["id"], tok)) as w:
        assert w.receive_json()["type"] == "presence_update"
        time.sleep(0.3)
        assert _status_of(client, ws["id"], tok, "idler") == "away"
        assert _collect(w) == []
        assert _status_of(client, ws["id"], tok, "idler") == "online"


def test_presence_frame_without_status_is_rejected(client):
    """``{"type":"presence"}`` used to mean "become online and lose your
    status message" — a default nobody asked for."""
    ws = _ws(client)
    tok = _member(client, ws["id"], "chooser")
    with client.websocket_connect(_presence_url(ws["id"], tok)) as w:
        assert w.receive_json()["type"] == "presence_update"
        as_user(client, "chooser")
        assert client.post(
            f"/workspaces/{ws['id']}/presence/me",
            json={"status": "away", "status_message": "lunch"},
        ).status_code == 200
        _collect(w)
        assert _collect(w, json.dumps({"type": "presence"})) == [
            {"type": "presence_error", "reason": "missing_status"}
        ]
        assert _status_of(client, ws["id"], tok, "chooser") == "away"


def test_unknown_status_answers_presence_error_not_pong(client):
    """A ``pong`` for a frame that changed nothing tells the client a lie."""
    ws = _ws(client)
    tok = _member(client, ws["id"], "sleeper")
    with client.websocket_connect(_presence_url(ws["id"], tok)) as w:
        assert w.receive_json()["type"] == "presence_update"
        _collect(w)
        assert _collect(w, json.dumps({"type": "presence", "status": "sleeping"})) == [
            {"type": "presence_error", "reason": "invalid_status"}
        ]


def test_non_string_status_is_not_stored(client):
    ws = _ws(client)
    tok = _member(client, ws["id"], "typist")
    with client.websocket_connect(_presence_url(ws["id"], tok)) as w:
        assert w.receive_json()["type"] == "presence_update"
        _collect(w)
        assert _collect(w, json.dumps({"type": "presence", "status": ["online"]})) == [
            {"type": "presence_error", "reason": "invalid_status"}
        ]


def test_malformed_json_is_answered(client):
    """Silence on a frame the server could not read is how a client hangs."""
    ws = _ws(client)
    tok = _member(client, ws["id"], "breaker")
    with client.websocket_connect(_presence_url(ws["id"], tok)) as w:
        assert w.receive_json()["type"] == "presence_update"
        _collect(w)
        assert _collect(w, '{"type": "presence", "status": "dnd"') == [
            {"type": "presence_error", "reason": "malformed_json"}
        ]
        assert _status_of(client, ws["id"], tok, "breaker") == "online"


def test_bye_frame_ends_the_session_and_goes_offline(client):
    """The endpoint docstring promised "last bye->offline" and never read a bye.

    Explicit leave matters because a tab that is being torn down should not have
    to wait for TCP teardown to be seen as gone.
    """
    ws = _ws(client)
    tok = _member(client, ws["id"], "leaver")
    with client.websocket_connect(_presence_url(ws["id"], tok)) as w:
        assert w.receive_json()["type"] == "presence_update"
        _collect(w)
        w.send_text(json.dumps({"type": "bye"}))
        assert _terminated(w), "the server answered instead of closing on bye"
    assert _status_of(client, ws["id"], tok, "leaver") == "offline"


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


# ---------------------------------------------------------------------------
# Multi-tab lifecycle: one presence row is shared by every socket a user holds,
# so ``online`` is written on the FIRST connect and ``offline`` only on the LAST
# close. Without this, closing any tab marks the user offline while they are
# still looking at the app.
# ---------------------------------------------------------------------------

def _presence_url(ws_id, token):
    return f"/ws/workspaces/{ws_id}/presence?session_token={token}"


def _open(client, ws_id, token, sessions):
    """Enter a WS test session outside a ``with`` block so closes can be ordered.

    Sessions are registered in ``sessions`` and unwound by each test's finally,
    so a mid-test assertion failure cannot leak a live socket into later tests.
    """
    session = client.websocket_connect(_presence_url(ws_id, token))
    session.__enter__()
    sessions.append(session)
    return session


def _close(session):
    session.__exit__(None, None, None)


def _sync(session):
    """Block until ``session``'s task has processed everything queued on it.

    A frame with an unknown status is a pure no-op server-side — it is rejected
    with ``presence_error`` and writes nothing — yet it is always answered,
    which is what makes it usable as a barrier.
    """
    session.send_text(json.dumps({"type": "presence", "status": "sleeping"}))
    while True:
        frame = session.receive_json()
        if frame["type"] in ("pong", "presence_error"):
            return


def _status_of(client, ws_id, token, user_id):
    rows = client.get(
        f"/workspaces/{ws_id}/presence", headers={"Authorization": f"Bearer {token}"}
    ).json()
    return next(r["status"] for r in rows if r["user_id"] == user_id)


def test_second_socket_close_keeps_user_online(client):
    ws = _ws(client)
    actor = _member(client, ws["id"], "actor")
    sessions = []
    try:
        _open(client, ws["id"], actor, sessions)  # first socket -> online
        second = _open(client, ws["id"], actor, sessions)
        _close(sessions[0])
        _sync(second)
        assert _status_of(client, ws["id"], actor, "actor") == "online"
    finally:
        for session in sessions:
            _close(session)


def test_last_socket_close_writes_offline(client):
    ws = _ws(client)
    actor = _member(client, ws["id"], "actor")
    sessions = []
    try:
        _open(client, ws["id"], actor, sessions)
        second = _open(client, ws["id"], actor, sessions)
        _close(sessions[0])
        assert _status_of(client, ws["id"], actor, "actor") == "online"
        _close(second)
        sessions.remove(second)
        assert _status_of(client, ws["id"], actor, "actor") == "offline"
    finally:
        for session in sessions:
            _close(session)


def test_second_socket_connect_keeps_explicit_status(client):
    """A second tab must not clobber a status the user chose deliberately."""
    ws = _ws(client)
    actor = _member(client, ws["id"], "actor")
    sessions = []
    try:
        _open(client, ws["id"], actor, sessions)
        client.post(
            f"/workspaces/{ws['id']}/presence/me",
            json={"status": "dnd"},
            headers={"Authorization": f"Bearer {actor}"},
        )
        _sync(_open(client, ws["id"], actor, sessions))
        assert _status_of(client, ws["id"], actor, "actor") == "dnd"
    finally:
        for session in sessions:
            _close(session)


def test_no_duplicate_online_broadcast(client):
    """Frames reach peers in order, so a spurious ``online`` from a second
    connect would overtake the ``dnd`` broadcast that follows it."""
    ws = _ws(client)
    viewer = _member(client, ws["id"], "viewer")
    actor = _member(client, ws["id"], "actor")
    sessions = []
    try:
        vs = _open(client, ws["id"], viewer, sessions)
        vs.receive_json()  # viewer's own online (broadcasts include the sender)
        _open(client, ws["id"], actor, sessions)
        first = vs.receive_json()
        assert (first["user_id"], first["status"]) == ("actor", "online")
        second = _open(client, ws["id"], actor, sessions)
        second.send_text(json.dumps({"type": "presence", "status": "dnd"}))
        while True:  # drain the actor's own copies until its pong
            if second.receive_json()["type"] == "pong":
                break
        peer = vs.receive_json()
        assert (peer["user_id"], peer["status"]) == ("actor", "dnd")
    finally:
        for session in sessions:
            _close(session)


def test_presence_socket_registry_freed(client):
    """The refcount dict must track live sockets and drop the key on the last
    close, or it grows one entry per historical member forever."""
    ws = _ws(client)
    actor = _member(client, ws["id"], "actor")
    other = _member(client, ws["id"], "other")
    key = (ws["id"], "actor")
    session = client.websocket_connect(_presence_url(ws["id"], actor))
    peer = client.websocket_connect(_presence_url(ws["id"], other))
    peer.__enter__()
    try:
        session.__enter__()
        assert len(presence._presence_sockets[key]) == 1
        second = client.websocket_connect(_presence_url(ws["id"], actor))
        second.__enter__()
        assert len(presence._presence_sockets[key]) == 2
        _close(second)
        assert key in presence._presence_sockets, "a held socket must keep the entry"
        _close(session)
    finally:
        _close(session)
        _close(peer)
    assert key not in presence._presence_sockets


def test_stale_online_decays_to_offline(client, monkeypatch):
    """A hard crash skips the socket's finally; read-time decay covers it."""
    ws = _ws(client)
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/presence/me", json={"status": "online"})
    monkeypatch.setattr(presence, "OFFLINE_AFTER_SECONDS", -1.0)
    assert client.get(f"/workspaces/{ws['id']}/presence").json()[0]["status"] == "offline"


def test_dnd_never_decays_to_offline(client, monkeypatch):
    ws = _ws(client)
    as_user(client, "owner")
    client.post(f"/workspaces/{ws['id']}/presence/me", json={"status": "dnd"})
    monkeypatch.setattr(presence, "OFFLINE_AFTER_SECONDS", -1.0)
    assert client.get(f"/workspaces/{ws['id']}/presence").json()[0]["status"] == "dnd"


def test_invalid_status_detail_is_string_form(client):
    """S6's error handling branches on this; nothing else pinned which of the
    endpoint's two 422 envelopes a caller gets for a bad enum value."""
    ws = _ws(client)
    as_user(client, "owner")
    r = client.post(f"/workspaces/{ws['id']}/presence/me", json={"status": "sleeping"})
    assert r.json()["detail"] == "Invalid presence status: sleeping"


# ---------------------------------------------------------------------------
# Activity-feed noise: presence is transient state, not a work event
# ---------------------------------------------------------------------------

def test_setting_presence_writes_no_activity_row(client):
    """Presence history lives in `PresenceState`; the Activity feed is for humans.

    Two reasons the old `log_activity(verb="set_presence")` was wrong rather than
    merely noisy: the socket path (`_set_and_publish`) never logged a row, so
    whether a status change appeared in the feed depended on which transport the
    user's client happened to use; and `services.log_activity` has no dedup or
    cooldown, so every deliberate click became a permanent row in a feed the
    overview renders at eight entries.
    """
    ws = _ws(client)
    token = _member(client, ws["id"], "actor")
    resp = client.post(
        f"/workspaces/{ws['id']}/presence/me",
        json={"status": "away"},
        headers={"Cookie": f"session_token={token}"},
    )
    assert resp.status_code == 200

    as_user(client, "owner")
    verbs = [a["verb"] for a in client.get(f"/workspaces/{ws['id']}/activity").json()]
    assert "set_presence" not in verbs, verbs


def test_presence_state_still_records_the_status(client):
    """The removal above must not lose the data — the row is the record."""
    ws = _ws(client)
    token = _member(client, ws["id"], "actor")
    client.post(
        f"/workspaces/{ws['id']}/presence/me",
        json={"status": "dnd", "status_message": "exam week"},
        headers={"Cookie": f"session_token={token}"},
    )
    as_user(client, "owner")
    rows = client.get(f"/workspaces/{ws['id']}/presence").json()
    mine = [r for r in rows if r["user_id"] == "actor"]
    assert [(r["status"], r["status_message"]) for r in mine] == [("dnd", "exam week")]
