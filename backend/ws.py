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
so no room ever retains a closed socket. Broadcasts additionally prune
sockets whose ``send`` raises, so a socket killed between joins and its
cleanup still cannot leak a delivery slot.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("stw.ws")

# Close codes (documented in docs/API.md). 4xxx range = application errors,
# so browsers/proxies do not confuse them with protocol failures.
WS_UNAUTHENTICATED = 4401  # no usable credential at handshake
WS_FORBIDDEN = 4403  # authenticated but not allowed in this channel
WS_NOT_FOUND = 4404  # channel does not exist
WS_BAD_HANDSHAKE = 4400  # malformed upgrade (bad subprotocol format)

# Subprotocol the client MUST offer to prove it read the WS contract.
# A raw browser ``new WebSocket(url)`` sends no subprotocol; the backend
# therefore still accepts the session_token cookie/query fallback, but a
# client that wants the negotiated path offers ``stw-ws`` explicitly.
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


async def _ws_send_safe(websocket, message: str) -> bool:
    """Send one frame; return False if the socket is gone."""
    try:
        await websocket.send_text(message)
        return True
    except Exception:  # noqa: BLE001 - any send failure means dead socket
        return False


async def _ws_broadcast(room_key: str, payload: dict[str, Any], exclude=None) -> int:
    """Fan out ``payload`` to every socket in ``room_key``.

    Returns the number of sockets that received the frame. Sockets whose
    send raises are pruned from the room (defensive cleanup for sockets
    that died before their endpoint ``finally`` ran).
    """
    room = _ws_rooms.get(room_key)
    if not room:
        return 0
    message = json.dumps(payload, ensure_ascii=False)
    dead: list = []
    delivered = 0
    for ws in list(room):
        if exclude is not None and ws is exclude:
            continue
        if await _ws_send_safe(ws, message):
            delivered += 1
        else:
            dead.append(ws)
    for ws in dead:
        room.discard(ws)
        if not room:
            _ws_rooms.pop(room_key, None)
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


def _ws_parse_ticket(header_value: str | None) -> str | None:
    """Extract the ticket from a ``Sec-WebSocket-Protocol`` header value.

    Returns None when the client did not offer our subprotocol (the cookie
    / query fallback still applies) or the value is malformed.
    """
    if not header_value:
        return None
    for candidate in (c.strip() for c in header_value.split(",")):
        if candidate == WS_SUBPROTOCOL:
            return ""
        if candidate.startswith(WS_SUBPROTOCOL + "."):
            ticket = candidate[len(WS_SUBPROTOCOL) + 1 :]
            return ticket or None
    return None
