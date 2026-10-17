"""Blocking work must not run on the loop that carries every open socket.

Each test here pins one call site to a thread by asserting where it executed, and
each was added for a different reason — bcrypt first, then the SMTP round-trip and
the upload's file I/O — so the file is about the loop, not about any one of them.
The bcrypt measurements below are the ones that established the shape of the
problem and they are the reason the assertion is positional rather than timed.

Measured with `bench/loop_blocking_probe.py` on `main` before this PR — SQLite,
in-process ASGI transport, 12 concurrent `POST /auth/register`:

    one bcrypt hash, timed alone      -> 290–352 ms
    3 registrations, awaited in order -> 1075–1310 ms
    12 concurrent registrations       -> 4945 ms  (14.7 hashes' worth of wall)
    worst loop tick gap in that batch -> 4904 ms

The last number is the realtime one. A 10 ms ticker sharing the process's event
loop went unserved for 4.9 seconds: every chat socket, every presence socket,
and the `WS_SEND_TIMEOUT_SECONDS` deadline that prunes wedged peers all live on
that loop, and `app._loop_stall_watchdog` calls anything over
`LOOP_STALL_WARN_SECONDS` (2 s) a stall. The batch could not overlap either —
the hash *is* the serialisation — so "a class signs up at once" was twelve
hashes of frozen realtime, not a parallel burst.

Why these tests assert a thread rather than a duration: a timing test measures
the runner, not the code, and passes for the wrong reason on an idle machine.
The invariant here is positional — bcrypt must execute where no event loop is
running — so it is checked positionally. Each spy records
`asyncio.get_running_loop()` from inside the real call: `RuntimeError` (no
running loop) is the pass, a loop is the failure. `_assert_off_loop` also
requires the spy to have run at all, so a patch pinned to a name the code never
calls fails loudly instead of passing on an empty dict.

The presence socket's two writes are **not** offloaded, and no test here asks
them to be: they cost p50 8–11 ms against a 20 s period, and putting
`_set_and_publish` behind a thread hop made `test_ws_connect_broadcasts_online`
hang instead of fail — a resumed step cannot send into another portal's socket.
The numbers and the reason are in `routers/presence.py:_set_and_publish`.
"""

import asyncio
import io
import threading

import bcrypt

from conftest import as_user

PASSWORD = "LoopProbe123!"


def _spy_on(monkeypatch, owner, name):
    """Wrap ``owner.name`` and record whether a loop was running where it ran."""
    real = getattr(owner, name)
    seen = {}

    def wrapper(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            seen["on_loop"] = False
        else:
            seen["on_loop"] = True
        seen["thread"] = threading.current_thread().name
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, wrapper)
    return seen


def _assert_off_loop(seen, what):
    assert "on_loop" in seen, f"{what} never ran: the spy is pinned to an unused name"
    assert not seen["on_loop"], (
        f"{what} ran on thread {seen['thread']!r}, which had a running event loop. "
        "A blocking call there stops every open WebSocket for its duration: the "
        "peers keep their TCP connection and receive nothing."
    )


def _register(client, email):
    resp = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return resp


def test_register_hashes_off_the_event_loop(client, monkeypatch):
    """One `hashpw` on the loop is the whole defect."""
    spy = _spy_on(monkeypatch, bcrypt, "hashpw")
    _register(client, "offloop-register@example.com")
    _assert_off_loop(spy, "bcrypt.hashpw")


def test_login_verifies_off_the_event_loop(client, monkeypatch):
    """Login is the hotter path, and a wrong password costs the same as a right one."""
    _register(client, "offloop-login@example.com")
    spy = _spy_on(monkeypatch, bcrypt, "checkpw")
    resp = client.post(
        "/auth/login", json={"email": "offloop-login@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    _assert_off_loop(spy, "bcrypt.checkpw")


def test_delete_account_verifies_off_the_event_loop(client, monkeypatch):
    """The third bcrypt call site — and the one a grep for `login` misses."""
    user_id = _register(client, "offloop-delete@example.com").json()["user"]["id"]
    as_user(client, user_id)
    spy = _spy_on(monkeypatch, bcrypt, "checkpw")
    gone = client.request("DELETE", "/users/me", json={"password": PASSWORD})
    assert gone.status_code == 200, gone.text
    _assert_off_loop(spy, "bcrypt.checkpw")


def _workspace_owner(client, email):
    """A registered user who owns one workspace, authenticated on `client`."""
    user_id = _register(client, email).json()["user"]["id"]
    as_user(client, user_id)
    ws = client.post(
        "/workspaces", json={"name": "Loop", "slug": "loop", "description": "x"}
    )
    assert ws.status_code == 201, ws.text
    return ws.json()


def test_invite_sends_mail_off_the_event_loop(client, monkeypatch):
    """`smtplib.SMTP(..., timeout=10)` inside `async def` is a 10 s loop stall.

    The stub path (no SMTP_HOST) is what runs here, and the assertion is still the
    right one: the invariant is *where* the send happens, not how long it takes.
    With `SMTP_HOST` set — which is what `email_sender` documents as the real
    configuration — the same call is a blocking network round-trip of up to the
    timeout, during which every chat and presence socket in the process is served
    nothing at all. The invite is committed first, so a mail failure cannot lose
    the invite and a retry is the caller's business.
    """
    import routers.invites as invites_module

    ws = _workspace_owner(client, "offloop-invite@example.com")
    spy = _spy_on(monkeypatch, invites_module, "send_invite_email")

    resp = client.post(
        f"/workspaces/{ws['id']}/invites",
        json={"email": "someone@example.com", "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    _assert_off_loop(spy, "send_invite_email")


def test_upload_reads_and_writes_off_the_event_loop(client, monkeypatch, tmp_path):
    """Both halves of an upload are blocking file I/O on the loop.

    `_stream_upload` reads the spooled request body in chunks and
    `_write_upload_bytes` puts the buffer on disk; at the default 25 MB cap either
    one is long enough to trip `_loop_stall_watchdog`, and the upload handler is
    `async def`.
    """
    import app as app_module
    import routers.files as files_module

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)

    ws = _workspace_owner(client, "offloop-upload@example.com")
    read_spy = _spy_on(monkeypatch, files_module, "_stream_upload")
    write_spy = _spy_on(monkeypatch, files_module, "_write_upload_bytes")

    resp = client.post(
        f"/workspaces/{ws['id']}/files",
        files={"file": ("probe.pdf", io.BytesIO(b"%PDF-1.4 probe"), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    _assert_off_loop(read_spy, "_stream_upload")
    _assert_off_loop(write_spy, "_write_upload_bytes")

