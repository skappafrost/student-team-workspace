"""Measure what a wedged WebSocket peer costs the rest of a room.

    python bench/ws_stall_probe.py [stall-seconds] [number-of-wedged-peers]

Joins one healthy socket plus *N* sockets that hold their ``send_text`` for
*stall-seconds* the way a half-open TCP does, then broadcasts and reports the
wall clock. Fan-out sits on the request path of
``POST /channels/{id}/messages``, so the second number is what a sender pays
once the broken peers have been found and pruned.

Before the bounded send (S6-RT4), one peer stalling 5s printed
``5.00s / delivered=2`` and the next three messages took ``15.03s``: the stalled
socket was waited on by everyone, every time, because it was never removed.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ws  # noqa: E402


class _Peer:
    def __init__(self, stall: float):
        self.stall = stall
        self.received = 0

    async def send_text(self, message: str) -> None:
        await asyncio.sleep(self.stall)
        self.received += 1


async def _main(stall: float, wedged: int) -> None:
    room = "chan:probe"
    peers = [_Peer(stall) for _ in range(wedged)]
    healthy = _Peer(0.0)
    for peer in peers:
        ws._ws_room_join(room, peer)
    ws._ws_room_join(room, healthy)
    print(
        f"WS_SEND_TIMEOUT_SECONDS = {getattr(ws, 'WS_SEND_TIMEOUT_SECONDS', 'not defined')}, "
        f"room size = {ws._ws_room_size(room)} ({wedged} wedged at {stall:.1f}s + 1 healthy)"
    )

    started = time.perf_counter()
    delivered = await ws._ws_broadcast(room, {"type": "new_message"})
    first = time.perf_counter() - started

    started = time.perf_counter()
    for _ in range(3):
        await ws._ws_broadcast(room, {"type": "new_message"})
    rest = time.perf_counter() - started

    print(
        f"first broadcast -> {first:.2f}s, delivered={delivered}, "
        f"healthy peer received {healthy.received}"
    )
    print(f"next three broadcasts -> {rest:.2f}s")
    still = sum(1 for peer in peers if peer in ws._ws_rooms.get(room, set()))
    print(f"wedged sockets still in the room: {still}")


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(_main(float(args[0]) if args else 5.0, int(args[1]) if len(args) > 1 else 1))
