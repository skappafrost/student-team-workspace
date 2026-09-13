"""T3-B03: request-id header, token-free logs, /healthz shape (real JWT only)."""

import logging

from conftest import as_user, clear_auth, make_user


def test_request_id_header_present(client):
    clear_auth(client)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id"), "middleware must attach X-Request-Id"


def test_request_id_echoes_incoming(client):
    clear_auth(client)
    resp = client.get("/health", headers={"X-Request-Id": "req-echo-123"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id") == "req-echo-123"


def test_token_never_appears_in_logs(client, caplog):
    fake = "FAKE-SECRET-TOKEN-never-log-9f8e7d6c5b4a"
    clear_auth(client)
    with caplog.at_level(logging.INFO, logger="stw.requests"):
        resp = client.get(
            "/health",
            headers={"Authorization": f"Bearer {fake}"},
            cookies={"session_token": fake},
        )
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id")
    assert fake not in caplog.text, "token/cookie material must never reach the logs"


def test_log_line_carries_real_user_id(client, db_session, caplog):
    make_user(db_session, "loguser")
    as_user(client, "loguser")
    try:
        with caplog.at_level(logging.INFO, logger="stw.requests"):
            caplog.clear()
            resp = client.get("/health")
        assert resp.status_code == 200
        assert "loguser" in caplog.text, "one info line must carry the JWT user id"
    finally:
        clear_auth(client)


def test_healthz_shape_without_creds(client):
    clear_auth(client)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "db_latency_ms" in data
    latency = data["db_latency_ms"]
    assert latency is None or (isinstance(latency, (int, float)) and latency >= 0)
    blob = resp.text.lower()
    assert "traceback" not in blob
    assert "sqlite:///" not in blob
    assert "database_url" not in blob
