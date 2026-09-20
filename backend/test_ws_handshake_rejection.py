"""What a refused WebSocket handshake actually puts on the wire.

docs/API.md used to promise that a rejection arrives as a documented 4401/4403/
4404 close code. It does not — and cannot. Measured against a real uvicorn (0.52)
with a `websockets` client:

    no credential            -> HTTP 403, close_code=None, empty body
    invalid token            -> HTTP 403, close_code=None, empty body
    unknown channel          -> HTTP 403, close_code=None, empty body
    stranger to the channel  -> HTTP 403, close_code=None, body
                                 '{"detail":"Not a workspace member"}'
    member, no subprotocol   -> CONNECTED
    member + `stw-ws` offer  -> CONNECTED (subprotocol 'stw-ws')

The code and the reason are destroyed by the transport, not by this app: uvicorn's
`websockets_sansio_impl` handles a `websocket.close` that arrives *before* the
accept by calling `conn.reject(HTTPStatus.FORBIDDEN, "")`, so every rejection
becomes a plain HTTP 403 and a browser reports the opaque failure its spec
reserves for an aborted connection. The one case with a body is an accident of
which code path refused it — a membership check that raises `HTTPException`
through a dependency gets Starlette's HTTP response instead, so that is the only
refusal that carries text. `TestClient` is why no test ever noticed any of this:
it raises `WebSocketDisconnect(code=…)` straight from the ASGI message, so the
pytest suite saw exactly the code the transport throws away.

Refusing before `accept()` is still the right behaviour — answering an
unauthenticated upgrade would hand the caller a live socket into a room it may not
see — so what is pinned here is the half this repository owns: the message the
application emits. Move a `close()` behind an `accept()` and these tests say so.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import models
from app import app as fastapi_app
from app import create_access_token
from conftest import as_user, make_user
from ws import WS_FORBIDDEN, WS_NOT_FOUND, WS_UNAUTHENTICATED


class _SendSpy:
    """ASGI wrapper recording every message the application sends."""

    def __init__(self, app):
        self.app = app
        self.sent: list[dict] = []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return

        async def _record(message):
            self.sent.append(dict(message))
            await send(message)

        await self.app(scope, receive, _record)


@pytest.fixture
def spy():
    """A socket opener that records what the application sent.

    HTTP still goes through the `client` fixture: it materializes the ``User`` row
    behind each JWT identity, and with FK enforcement on, a workspace create for a
    ghost user 500s instead of testing anything.
    """
    spy_app = _SendSpy(fastapi_app)
    return TestClient(spy_app), spy_app


def _channel(client, owner: str, name: str = "rej-general") -> str:
    as_user(client, owner)
    resp = client.post(
        "/workspaces",
        json={"name": f"REJ {name}", "slug": f"rej-{name}", "description": "x"},
    )
    assert resp.status_code == 201, resp.text
    chan = client.post(
        f"/workspaces/{resp.json()['id']}/channels", json={"name": name, "type": "general"}
    )
    assert chan.status_code == 201, chan.text
    return chan.json()["id"]


def _refuse(spy, path: str, token: str | None = None) -> None:
    """Open a socket expected to be refused, and swallow the disconnect."""
    client, _ = spy
    url = f"{path}?session_token={token}" if token else path
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url):
            pass


def _assert_refused_with(spy, code: int) -> None:
    """The refusal is the first thing on the wire, and no accept precedes it."""
    _, recorder = spy
    assert not [m for m in recorder.sent if m["type"] == "websocket.accept"], (
        "the socket was accepted before being refused — the close code would then "
        "be reachable, and so would a frame on a room the caller may not join"
    )
    closes = [m for m in recorder.sent if m["type"] == "websocket.close"]
    assert closes, (
        "no websocket.close was emitted; the application sent "
        f"{[m['type'] for m in recorder.sent]}"
    )
    assert closes[0]["code"] == code, f"expected {code}, the application sent {closes[0]!r}"


def _assert_refused_as_http_response(spy, contains: str) -> None:
    """The other shape a refusal takes here, and why it is asserted separately.

    An ``HTTPException`` raised by a route dependency leaves Starlette to answer
    the upgrade with ``websocket.http.response.*`` — a 403 with a JSON body —
    while the endpoints' own `close(code=…)` calls produce the 4xxx message. Same
    refusal, two wire shapes, decided by which code path produced it: measured on
    a live server, the chat non-member case is the only one whose 403 carries
    `{"detail": …}` and the rest arrive empty-bodied. Nothing may branch on that,
    which is the point of this test existing next to the other one.
    """
    _, recorder = spy
    assert not [m for m in recorder.sent if m["type"] == "websocket.accept"], (
        "the socket was accepted before being refused"
    )
    assert not [m for m in recorder.sent if m["type"] == "websocket.close"], (
        f"expected the HTTP-response shape, saw {recorder.sent}"
    )
    start = next(
        (m for m in recorder.sent if m["type"] == "websocket.http.response.start"), None
    )
    assert start and start["status"] == 403, recorder.sent
    body = b"".join(
        m.get("body", b"") for m in recorder.sent if m["type"] == "websocket.http.response.body"
    )
    assert contains in body.decode(), body


def test_missing_credential_sends_4401_before_any_accept(client, spy):
    channel = _channel(client, "rej-owner-a")
    _refuse(spy, f"/ws/channels/{channel}")
    _assert_refused_with(spy, WS_UNAUTHENTICATED)


def test_invalid_token_sends_4401(client, spy):
    channel = _channel(client, "rej-owner-b")
    _refuse(spy, f"/ws/channels/{channel}", "not-a-real-token")
    _assert_refused_with(spy, WS_UNAUTHENTICATED)


def test_unknown_channel_sends_4404(client, spy):
    _channel(client, "rej-owner-c")
    _refuse(spy, "/ws/channels/no-such-channel", create_access_token("rej-owner-c"))
    _assert_refused_with(spy, WS_NOT_FOUND)


def test_non_member_is_refused_without_ever_being_accepted(client, spy, db_session):
    """The refusal shape differs by code path, so the code is not asserted here.

    `WS_FORBIDDEN` is what the endpoint *means* to send; what this path actually
    puts on the wire is Starlette's 403 response, because the membership check
    raises through a dependency instead of calling `close()` itself. See
    `_assert_refused_as_http_response`.
    """
    channel = _channel(client, "rej-owner-d")
    make_user(db_session, "rej-outsider")
    _refuse(spy, f"/ws/channels/{channel}", create_access_token("rej-outsider"))
    _assert_refused_as_http_response(spy, "Not a workspace member")


def test_guest_presence_sends_4403(client, spy, db_session):
    """Presence refuses guests outright, and the reason is the same code."""
    as_user(client, "rej-pres-owner")
    make_user(db_session, "rej-guest")
    ws = client.post("/workspaces", json={"name": "REJP", "slug": "rej-p", "description": "x"})
    assert ws.status_code == 201, ws.text
    workspace_id = ws.json()["id"]
    db_session.add(
        models.WorkspaceMembership(workspace_id=workspace_id, user_id="rej-guest", role="guest")
    )
    db_session.commit()
    _refuse(spy, f"/ws/workspaces/{workspace_id}/presence", create_access_token("rej-guest"))
    _assert_refused_with(spy, WS_FORBIDDEN)
