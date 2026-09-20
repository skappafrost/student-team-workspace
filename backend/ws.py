"""In-memory WebSocket room manager for channel + user broadcasts.

Two room namespaces exist, keyed by plain strings:

* ``chan:<channel_id>`` — every authenticated member socket of a channel.
  Message/typing/reaction frames fan out here.
* ``user:<user_id>`` — every socket owned by one user (typically one per
  browser tab). ``notification_created`` frames fan out here so an open
  tab's notification badge updates without polling.

Both namespaces share one registry so disconnect cleanup is uniform.

Connection lifecycle contract (kept out of this module, enforced by
``routers/channels.py``): a socket joins a room only AFTER the handshake
was accepted, and the endpoint's ``finally`` must call :func:`_ws_room_leave`
so no room ever retains a closed socket. Broadcasts send to every peer of a
room concurrently, and prune any socket whose ``send`` raises or exceeds
:data:`WS_SEND_TIMEOUT_SECONDS`, so a socket killed between joins and its
cleanup — or one whose TCP is simply wedged — cannot leak a delivery slot or
charge its latency to the rest of the room.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("stw.ws")

#: How long one peer gets to accept a frame before it is treated as dead.
#: A healthy local send is sub-millisecond, so this only ever fires on a socket
#: that is wedged or gone — and it bounds the worst case a *sender's* request can
#: be charged for someone else's broken connection.
WS_SEND_TIMEOUT_SECONDS = 2.0

# Close codes. The values are the application's own vocabulary and are asserted
# by `test_ws_handshake_rejection.py`, but read § Handshake rejection codes in
# docs/API.md before treating them as something a browser can observe: a close
# sent before `accept()` never reaches a client, because the transport turns it
# into an HTTP 403 rejection.
WS_UNAUTHENTICATED = 4401  # no usable credential at handshake
WS_FORBIDDEN = 4403  # authenticated but not allowed in this channel
WS_NOT_FOUND = 4404  # channel does not exist

# Subprotocol the client MUST offer to prove it read the WS contract.
# A raw browser ``new WebSocket(url)`` sends no subprotocol; the backend
# therefore still accepts the session_token cookie/query fallback, but a
# client that wants the negotiated path offers ``stw-ws`` explicitly.
# A reply may only ever name a string the client offered — see
# :func:`_ws_negotiate_subprotocol`.
WS_SUBPROTOCOL = "stw-ws"


_ws_rooms: dict[str, set] = {}


def _ws_room_join(room_key: str, websocket) -> None:
    _ws_rooms.setdefault(room_key, set()).add(websocket)


def _ws_room_leave(room_key: str, websocket) -> None:
    room = _ws_rooms.get(room_key)
    if room:
        room.discard(websocket)
        if not room:
            _ws_rooms.pop(room_key, None)


def _ws_room_size(room_key: str) -> int:
    return len(_ws_rooms.get(room_key, ()))


async def _ws_send_safe(websocket, message: str, room_key: str) -> bool:
    """Send one frame within :data:`WS_SEND_TIMEOUT_SECONDS`; False if we could not.

    The failure is logged because a silently-swallowed exception here was how
    every browser socket in this app died: the handshake got far enough to join
    a room, the first send raised, and a broadcast reported ``delivered=0``
    while the room still looked populated.

    The timeout is the other half of that story. A half-open TCP does not raise,
    it stalls: ``await websocket.send_text`` never returns, so without a bound a
    single wedged peer decided how long every *other* member waited — and paid
    for it again on every subsequent message, on the request path of
    ``POST /channels/{id}/messages``.
    """
    try:
        await asyncio.wait_for(websocket.send_text(message), WS_SEND_TIMEOUT_SECONDS)
        return True
    except TimeoutError:
        logger.warning(
            "ws send timed out after %.1fs; dropping socket from room=%s",
            WS_SEND_TIMEOUT_SECONDS,
            room_key,
        )
        return False
    except Exception as exc:  # noqa: BLE001 - any send failure means dead socket
        logger.warning("ws send failed; dropping socket from room=%s: %s", room_key, exc)
        return False


async def _ws_broadcast(room_key: str, payload: dict[str, Any], exclude=None) -> int:
    """Fan out ``payload`` to every socket in ``room_key``.

    Returns the number of sockets that received the frame. Sockets whose send
    raises or times out are pruned from the room (defensive cleanup for sockets
    that died before their endpoint ``finally`` ran), so one wedged peer is paid
    for once instead of on every message.

    The sends are deliberately inline, not ``asyncio.gather``: gathering wraps
    each one in a task, which defers the frame by a scheduler tick, and a
    ``TestClient`` websocket session runs *each socket on its own portal event
    loop*. A deferred cross-loop send then lands in a peer stream whose receiver
    has already parked, and anyio never wakes it — measured as
    ``test_ws_connect_broadcasts_online`` hanging with the peer blocked in
    ``receive_json()``. `asyncio.wait_for` keeps the call inline (since 3.12 it
    is just a timeout context around the await), so the bound costs nothing the
    old code did not already do.
    """
    room = _ws_rooms.get(room_key)
    if not room:
        return 0
    message = json.dumps(payload, ensure_ascii=False)
    targets = [ws for ws in list(room) if exclude is None or ws is not exclude]
    delivered_flags = [await _ws_send_safe(ws, message, room_key) for ws in targets]
    dead = [ws for ws, ok in zip(targets, delivered_flags, strict=True) if not ok]
    delivered = len(targets) - len(dead)
    for ws in dead:
        room.discard(ws)
        if not room:
            _ws_rooms.pop(room_key, None)
    # DEBUG, not INFO: this fires on every frame, so at chat volume an INFO line
    # costs more than it tells anyone. It exists because a `delivered` of 0 in a
    # room that still looks populated is the exact signature of a handshake that
    # the browser refused, and that is worth being able to see with one flag.
    logger.debug(
        "broadcast room=%s delivered=%d room_size_after=%d",
        room_key,
        delivered,
        len(room),
    )
    return delivered


def _ws_room_key_channel(channel_id: str) -> str:
    return f"chan:{channel_id}"


def _ws_room_key_user(user_id: str) -> str:
    return f"user:{user_id}"


def _ws_room_key_workspace(workspace_id: str) -> str:
    """Presence fan-out room: every socket of a workspace's members.

    Distinct from ``chan:`` (per-channel message fan-out) so a status change
    reaches a member on any channel they have open, not just the one socket
    they are reading. Members-only by construction: a socket joins only after
    the endpoint has verified workspace membership.
    """
    return f"workspace:{workspace_id}"


async def _ws_broadcast_channel(channel_id: str, payload: dict, exclude=None) -> int:
    """Broadcast to every member socket of a channel room."""
    return await _ws_broadcast(_ws_room_key_channel(channel_id), payload, exclude=exclude)


async def _ws_broadcast_workspace(workspace_id: str, payload: dict, exclude=None) -> int:
    """Broadcast a workspace-scoped frame (presence updates) to member sockets."""
    return await _ws_broadcast(_ws_room_key_workspace(workspace_id), payload, exclude=exclude)


async def _ws_broadcast_user(user_id: str, payload: dict) -> int:
    """Broadcast to every socket owned by ``user_id`` (all their tabs).

    Used for ``notification_created``: the notification target is a user,
    not a channel, and an open tab should learn about it immediately.
    """
    return await _ws_broadcast(_ws_room_key_user(user_id), payload)


async def _ws_notify_user(user_id: str, notification_out: dict) -> None:
    """Push one notification to a user's own sockets (TA4-2).

    ``notification_out`` is the already-serialized ``NotificationOut`` dict
    (the same shape ``GET /notifications`` returns), so a client can merge
    the frame into its notification list without a second request.
    """
    if not user_id:
        return
    await _ws_broadcast_user(
        user_id,
        {"type": "notification_created", "notification": notification_out},
    )


def _ws_ticket_subprotocol(ticket: str) -> str:
    """Encode a short-lived ticket as the negotiated subprotocol value.

    Format: ``stw-ws.<ticket>``. The prefix is the part the server matches
    on; the suffix is opaque transport for the ticket itself and is not
    interpreted here.
    """
    return f"{WS_SUBPROTOCOL}.{ticket}" if ticket else WS_SUBPROTOCOL


def _ws_negotiate_subprotocol(header_value: str | None) -> tuple[str | None, str | None]:
    """``(ticket, candidate_to_echo)`` for a ``Sec-WebSocket-Protocol`` header.

    The second element is the client's *verbatim* offered string, which is the
    only thing the server may name in its reply: RFC 6455 §4.1 step 6 makes a
    browser fail the handshake when ``Sec-WebSocket-Protocol`` names a protocol
    it did not offer. Neither Starlette's ``accept()`` nor uvicorn checks this
    (uvicorn's ``websockets_impl.process_subprotocol`` deliberately echoes
    whatever the app sent), so the endpoint has to get it right itself.

    Returns ``(None, None)`` when the client offered nothing we support — the
    raw ``new WebSocket(url)`` browser case — in which case the server must
    send no ``Sec-WebSocket-Protocol`` header at all.
    """
    if not header_value:
        return (None, None)
    for candidate in (c.strip() for c in header_value.split(",")):
        if candidate == WS_SUBPROTOCOL:
            return ("", candidate)
        if candidate.startswith(WS_SUBPROTOCOL + "."):
            ticket = candidate[len(WS_SUBPROTOCOL) + 1 :]
            if ticket:
                return (ticket, candidate)
    return (None, None)
