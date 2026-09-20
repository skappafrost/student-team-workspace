"""Measure what one bcrypt costs the event loop that carries every socket.

    python bench/loop_blocking_probe.py [concurrency]

``POST /auth/register`` and ``POST /auth/login`` hash and verify passwords, and
a 12-round bcrypt measured 264–352 ms on this machine (it drifts with CPU
frequency, so read the ratios, not the absolutes). While that runs on the
process's one event loop, no WebSocket frame is read, written or timed out —
chat, presence, and the ``WS_SEND_TIMEOUT_SECONDS`` deadline all wait.

The probe drives the request path in-process (ASGI transport, temp SQLite) and
reports wall clock for *concurrency* registrations plus the worst gap a 10 ms
ticker on the same loop observed. The ticker is the realtime number: it is how
long every open socket in the process went unserved.

Before the offload (S6-RT5), 12 concurrent registrations:

    4945 ms wall — 14.7 hashes' worth, i.e. fully serial
    4904 ms worst loop tick gap

After, same machine, three runs:

    1106 / 1148 / 1288 ms wall — 4.2 / 4.3 / 4.7 hashes
    110 / 151 / 123 ms worst loop tick gap

What is left after the fix scales with the request count, not the hash cost
(4 → 54 ms, 8 → 92 ms, 12 → ~130 ms), which identifies it as the ~11 ms of
synchronous SQLAlchemy still on every request path — not bcrypt.

Above 15 concurrent requests the batch stops measuring bcrypt at all: the
engine's QueuePool is ``size 5 + overflow 10``, so the sixteenth request cannot
check out a connection and returns 500 (measured at 20: exactly five 500s, each
after 151.5 s — far past the pool's own 30 s timeout, which is a finding in
itself). The probe says so instead of printing a traceback.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROOT = tempfile.mkdtemp(prefix="stw-loop-probe-")
os.environ["DATABASE_URL"] = f"sqlite:///{_ROOT}/probe.db"
os.environ["ENVIRONMENT"] = "test"

import bcrypt  # noqa: E402
import httpx  # noqa: E402

import app as app_module  # noqa: E402
import models  # noqa: E402
import routers.presence as presence  # noqa: E402
from database import Base, engine, get_db  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("stw.requests").setLevel(logging.WARNING)

#: SQLAlchemy's default `QueuePool(size=5, max_overflow=10)` for this engine.
POOL_CEILING = 15


class _Ticker:
    """Counts the longest gap between two 10 ms ticks on this loop."""

    def __init__(self):
        self.worst = 0.0
        self._stop = False

    async def run(self):
        last = time.perf_counter()
        while not self._stop:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            self.worst = max(self.worst, now - last - 0.01)
            last = now

    def stop(self):
        self._stop = True


async def _register(client: httpx.AsyncClient, email: str) -> int:
    resp = await client.post("/auth/register", json={"email": email, "password": "ProbePass123!"})
    return resp.status_code


def _percentiles(fn: Callable[[], None], samples: int = 50) -> tuple[float, float]:
    """``(p50, p95)`` in ms for a synchronous call, after two warm-up runs."""
    fn()
    fn()
    taken = []
    for _ in range(samples):
        started = time.perf_counter()
        fn()
        taken.append((time.perf_counter() - started) * 1000)
    taken.sort()
    return taken[len(taken) // 2], taken[int(len(taken) * 0.95)]


def _measure_presence_writes() -> tuple[tuple[float, float], tuple[float, float]]:
    """Time the two writes the presence socket performs inline on its loop.

    These are the numbers behind *not* offloading them — see
    ``routers/presence.py:_set_and_publish``. The DB calls are the same ones the
    socket makes, on the same session factory, minus the fan-out.
    """
    from database import SessionLocal
    from models import User, Workspace, WorkspaceMembership

    with SessionLocal() as seed:
        seed.add(User(id="probe-user", email="probe-user@example.com", display_name="p"))
        seed.add(Workspace(id="probe-ws", name="Probe", slug="probe-ws", description="x"))
        seed.add(
            WorkspaceMembership(workspace_id="probe-ws", user_id="probe-user", role="owner")
        )
        seed.commit()

    def heartbeat() -> None:
        db = next(get_db())
        try:
            presence.touch_presence(db, user_id="probe-user", workspace_id="probe-ws")
        finally:
            db.close()

    def transition() -> None:
        db = next(get_db())
        try:
            row = presence.set_presence(
                db, user_id="probe-user", workspace_id="probe-ws", status="dnd"
            )
            db.get(models.User, "probe-user")
            presence._row_out(row, "probe-user", "p")
        finally:
            db.close()

    return _percentiles(heartbeat), _percentiles(transition)


async def _main(concurrency: int) -> int:
    Base.metadata.create_all(engine)

    started = time.perf_counter()
    bcrypt.hashpw(b"ProbePass123!", bcrypt.gensalt())
    single = time.perf_counter() - started
    heartbeat, transition = _measure_presence_writes()

    # `raise_app_exceptions=False` keeps a 500 a status code, the way uvicorn
    # delivers it; the default would re-raise the server error here instead.
    transport = httpx.ASGITransport(app=app_module.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        started = time.perf_counter()
        codes = [await _register(client, f"s{i}-{uuid.uuid4().hex}@example.com") for i in range(3)]
        serial = time.perf_counter() - started
        if codes != [201, 201, 201]:
            print(f"serial registrations returned {codes}, expected 201 — nothing measured")
            return 1

        ticker = _Ticker()
        task = asyncio.get_running_loop().create_task(ticker.run())
        await asyncio.sleep(0.05)
        started = time.perf_counter()
        emails = [f"c{i}-{uuid.uuid4().hex}@example.com" for i in range(concurrency)]
        codes = await asyncio.gather(*[_register(client, e) for e in emails])
        overlapped = time.perf_counter() - started
        ticker.stop()
        await task

    print(f"one bcrypt hash, timed alone          -> {single * 1000:.0f} ms")
    print(f"3 registrations, awaited in order     -> {serial * 1000:.0f} ms")
    print(
        f"{concurrency:>2} concurrent registrations       -> {overlapped * 1000:.0f} ms "
        f"({overlapped / single:.1f} hashes' worth of wall clock)"
    )
    print(f"worst loop tick gap in that batch     -> {ticker.worst * 1000:.0f} ms")
    print(
        "on the loop the hashes cannot overlap and one tick gap is a whole hash; "
        "off the loop they run in parallel and no gap reaches one."
    )
    print(
        f"presence heartbeat write, inline    -> p50 {heartbeat[0]:.1f} ms / p95 {heartbeat[1]:.1f} ms"
    )
    print(
        f"presence transition write, inline   -> p50 {transition[0]:.1f} ms / "
        f"p95 {transition[1]:.1f} ms"
    )
    print(
        "the two presence writes stay on the loop on purpose: 20s apart per tab, "
        "and offloading `_set_and_publish` parks the cross-socket fan-out under "
        "TestClient (routers/presence.py)."
    )

    failed = [code for code in codes if code != 201]
    if failed:
        print(
            f"\n{len(failed)} of {concurrency} registrations did not return 201 "
            f"(statuses: {sorted(set(failed))}). Past {POOL_CEILING} concurrent requests the "
            "engine's QueuePool (size 5 + overflow 10) runs dry, and a request that cannot "
            "check out a connection 500s. Its own 30s `pool_timeout` does not explain the "
            "elapsed time — the failures above land far past it — which is part of why the "
            "ceiling is its own open defect. The timings above are a measurement of pool "
            "starvation, not of bcrypt."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(int(sys.argv[1]) if len(sys.argv) > 1 else 12)))
