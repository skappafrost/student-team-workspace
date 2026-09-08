"""In-memory WebSocket room manager for channel broadcasts."""

# Maps channel_id -> set of active WebSocket connections.
_ws_rooms: dict[str, set] = {}


def _ws_room_join(channel_id: str, websocket) -> None:
    _ws_rooms.setdefault(channel_id, set()).add(websocket)


def _ws_room_leave(channel_id: str, websocket) -> None:
    room = _ws_rooms.get(channel_id)
    if room:
        room.discard(websocket)
        if not room:
            _ws_rooms.pop(channel_id, None)


async def _ws_broadcast(channel_id: str, payload: dict) -> None:
    import json

    room = _ws_rooms.get(channel_id)
    if not room:
        return
    message = json.dumps(payload)
    dead = []
    for ws in list(room):
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        room.discard(ws)
        _ws_room_leave(channel_id, ws)
