"""Unit tests for backend/email_sender.py (T3-B01).

Covers: SMTP send path (monkeypatched smtplib), SMTP failure path (never
raises, returns email_sent False), stub redaction (token hidden by default,
visible only with LOG_FULL_INVITE_LINK=1), and an endpoint smoke test proving
the invite endpoint still returns 201 while ignoring the sender's return
value (schemas.py intentionally untouched).
"""

import logging

import pytest

import email_sender
from conftest import as_user


class _FakeSMTP:
    """Minimal smtplib.SMTP stand-in recording sent messages."""

    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_called = False
        self.login_args = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                "SMTP_FROM", "LOG_FULL_INVITE_LINK"):
        monkeypatch.delenv(var, raising=False)
    _FakeSMTP.instances.clear()
    yield
    _FakeSMTP.instances.clear()


def test_smtp_send_path(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "s3cret")
    monkeypatch.setattr(email_sender.smtplib, "SMTP", _FakeSMTP)

    result = email_sender.send_invite_email(
        email="bob@example.com",
        token="tok-abc-123",
        workspace_name="Acme",
        invite_url="https://app.example.com/invite/tok-abc-123",
    )

    assert result == {"email_sent": True}
    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("mail.example.com", 587)
    assert smtp.starttls_called is True
    assert smtp.login_args == ("bot@example.com", "s3cret")
    assert len(smtp.sent) == 1
    assert smtp.sent[0]["To"] == "bob@example.com"


def test_smtp_failure_returns_false_never_raises(monkeypatch, caplog):
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")

    def _boom(host, port, timeout=None):
        raise ConnectionError("smtp down")

    monkeypatch.setattr(email_sender.smtplib, "SMTP", _boom)

    with caplog.at_level(logging.WARNING):
        result = email_sender.send_invite_email(
            email="bob@example.com",
            token="tok-abc-123",
            workspace_name="Acme",
        )

    assert result == {"email_sent": False}
    assert "bob@example.com" in caplog.text


def test_stub_redacts_token_by_default(monkeypatch, caplog):
    secret = "tok-super-secret-999"
    with caplog.at_level(logging.INFO):
        result = email_sender.send_invite_email(
            email="bob@example.com",
            token=secret,
            workspace_name="Acme",
            invite_url=f"https://app.example.com/invite/{secret}",
        )

    assert result == {"email_sent": False}
    assert secret not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert "bob@example.com" in caplog.text


def test_stub_full_link_opt_in(monkeypatch, caplog):
    monkeypatch.setenv("LOG_FULL_INVITE_LINK", "1")
    secret = "tok-visible-123"
    with caplog.at_level(logging.INFO):
        email_sender.send_invite_email(
            email="bob@example.com",
            token=secret,
            workspace_name="Acme",
        )

    assert secret in caplog.text


def test_invite_endpoint_ignores_sender_return(client):
    """Endpoint compat: still 201 + InviteOut shape with the new sender."""
    as_user(client, "alice-smtp")
    ws = client.post("/workspaces", json={"name": "SMTP WS", "slug": "smtp-ws"})
    assert ws.status_code == 201
    ws_id = ws.json()["id"]

    response = client.post(
        f"/workspaces/{ws_id}/invites",
        json={"email": "bob@example.com", "role": "member"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "bob@example.com"
    assert data["workspace_id"] == ws_id
    assert "token" in data
