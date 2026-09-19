"""The server may only name a WebSocket subprotocol the client offered.

RFC 6455 §4.1 step 6 makes a browser FAIL the handshake when the 101 response
carries ``Sec-WebSocket-Protocol`` naming a protocol it did not offer. Nothing
in this stack enforces that, which is how every browser socket in the app died
just after a successful-looking upgrade while the whole pytest WS suite stayed
green:

* ``starlette.websockets.WebSocket.accept()`` copies ``subprotocol`` straight
  into the ASGI ``websocket.accept`` message without comparing it to the offer,
* ``uvicorn.protocols.websockets.websockets_impl`` overrides
  ``process_subprotocol`` to "return whatever subprotocol is sent in the
  'accept' message",
* ``starlette.testclient`` *records* ``accepted_subprotocol`` and never
  validates it, and no test in this repo passes ``subprotocols=``.

So the rule is asserted here, at the only seam where both ends of the real
contract are visible: the ``websocket.accept`` message the application emits,
against the ``subprotocols`` the client put in the scope.
"""

import pytest
from fastapi.testclient import TestClient

from app import app as fastapi_app
from app import create_access_token
from conftest import as_user
from database import get_db


class _AcceptSpy:
    """ASGI wrapper that records the ``websocket.accept`` message.

    It deliberately does NOT raise inside ``send``: an exception thrown from
    the send channel surfaces through Starlette's error handling as something
    other than the assertion under test. Recording and asserting after the
    context block exits keeps the failure message honest.
    """

    def __init__(self, app):
        self.app = app
        self.last = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return

        async def _send(message):
            if message["type"] == "websocket.accept":
                self.last = {
                    "offered": list(scope.get("subprotocols") or []),
                    "picked": message.get("subprotocol"),
                }
            await send(message)

        await self.app(scope, receive, _send)


@pytest.fixture
def spy_client(db_session):
    """A ``client``-shaped TestClient whose accept() messages are recorded.

    Reuses ``db_session`` (pytest hands the same session to both fixtures in a
    test), so workspaces created through the plain ``client`` fixture are
    visible to the socket opened here.
    """

    def _get_db_override():
        return db_session

    fastapi_app.dependency_overrides[get_db] = _get_db_override
    spy = _AcceptSpy(fastapi_app)
    yield TestClient(spy), spy
    fastapi_app.dependency_overrides.clear()


def _channel(client, user_id: str, name: str = "hs-general") -> str:
    as_user(client, user_id)
    resp = client.post(
        "/workspaces",
        json={"name": f"HS {name}", "slug": f"hs-{name}", "description": "x"},
    )
    assert resp.status_code == 201
    chan = client.post(
        f"/workspaces/{resp.json()['id']}/channels",
        json={"name": name, "type": "general"},
    )
    assert chan.status_code == 201
    return chan.json()["id"]


def _workspace(client, user_id: str) -> str:
    as_user(client, user_id)
    resp = client.post(
        "/workspaces",
        json={
            "name": f"HS-PRES {user_id}",
            "slug": f"hs-pres-{user_id}",
            "description": "x",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _assert_legal(spy):
    assert spy.last is not None, "endpoint never reached accept()"
    picked, offered = spy.last["picked"], spy.last["offered"]
    if picked is not None:
        assert picked in offered, (
            f"server named {picked!r} but the client offered {offered!r}; "
            "RFC 6455 4.1 step 6 makes the browser abort the handshake there"
        )


def test_channel_socket_offers_nothing_to_a_browser(client, spy_client):
    """The exact browser shape: ``new WebSocket(url)`` + session cookie, no offer."""
    chan_id = _channel(client, "hs-raw-owner")
    token = create_access_token("hs-raw-owner")
    with spy_client[0].websocket_connect(
        f"/ws/channels/{chan_id}", headers={"Cookie": f"session_token={token}"}
    ):
        pass
    _assert_legal(spy_client[1])


def test_channel_socket_cookie_query_offers_nothing(client, spy_client):
    chan_id = _channel(client, "hs-query-owner")
    token = create_access_token("hs-query-owner")
    with spy_client[0].websocket_connect(
        f"/ws/channels/{chan_id}?session_token={token}"
    ):
        pass
    _assert_legal(spy_client[1])


def test_presence_socket_offers_nothing(client, spy_client):
    ws_id = _workspace(client, "hs-pres-owner")
    token = create_access_token("hs-pres-owner")
    with spy_client[0].websocket_connect(
        f"/ws/workspaces/{ws_id}/presence?session_token={token}"
    ):
        pass
    _assert_legal(spy_client[1])


def test_channel_socket_echoes_the_exact_candidate_offered(client, spy_client):
    """A client that did offer a protocol must get that same string back.

    Dev/test mode returns the bare ``stw-ws`` from ``POST /auth/ws-ticket``
    (tickets are disabled outside production), so that is the value offered
    here; the point is not which string, it is that the reply equals an offer.
    """
    chan_id = _channel(client, "hs-ticket-owner")
    minted = client.post("/auth/ws-ticket")
    assert minted.status_code == 200
    offered = minted.json()["subprotocol"]
    token = create_access_token("hs-ticket-owner")
    with spy_client[0].websocket_connect(
        f"/ws/channels/{chan_id}?session_token={token}", subprotocols=[offered]
    ):
        pass
    _assert_legal(spy_client[1])
    assert spy_client[1].last["picked"] == offered, (
        "a client that offered a protocol must get that exact string back"
    )


def test_negotiation_returns_the_verbatim_offer():
    """``stw-ws.<ticket>`` is one candidate; echoing bare ``stw-ws`` is illegal."""
    from ws import _ws_negotiate_subprotocol

    assert _ws_negotiate_subprotocol("stw-ws.abc123") == ("abc123", "stw-ws.abc123")
    assert _ws_negotiate_subprotocol("stw-ws") == ("", "stw-ws")
    assert _ws_negotiate_subprotocol(None) == (None, None)
    assert _ws_negotiate_subprotocol("chat, stw-ws.abc") == ("abc", "stw-ws.abc")
    assert _ws_negotiate_subprotocol("stw-ws.") == (None, None)
    assert _ws_negotiate_subprotocol("mqtt, chat") == (None, None)
