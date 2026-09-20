"""The loop-stall watchdog must be proven to fire.

`app._loop_stall_watchdog` is the instrument behind a negative result: the load
run reported zero stalls, and "zero" from an unproven sensor is not evidence. So
this pins the sensor itself — block the loop past the threshold and require the
warning. If the watchdog ever stops working, this fails rather than quietly
reporting a healthy loop forever.
"""

import asyncio
import logging
import time

import app as app_module


async def _collect(loop, seconds):
    task = loop.create_task(app_module._loop_stall_watchdog())
    await asyncio.sleep(seconds)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_watchdog_reports_a_stall_it_should_see(caplog):
    """A blocking call longer than the threshold has to be named in the log."""
    with caplog.at_level(logging.WARNING, logger="stw.loop"):
        async def scenario():
            loop = asyncio.get_running_loop()
            collector = loop.create_task(_collect(loop, 5.0))
            await asyncio.sleep(0.2)  # let the watchdog take its first baseline
            time.sleep(app_module.LOOP_STALL_WARN_SECONDS + 1.5)  # the stall
            await collector

        asyncio.run(scenario())

    stalls = [r for r in caplog.records if "event loop stalled" in r.getMessage()]
    assert stalls, (
        "the watchdog never reported a 3.5s blocking stall; the sensor is broken "
        "and every 'no stalls' reading from it is meaningless"
    )


def test_watchdog_stays_quiet_on_a_healthy_loop(caplog):
    """The other half: without a stall it must not cry wolf."""
    with caplog.at_level(logging.WARNING, logger="stw.loop"):
        async def scenario():
            loop = asyncio.get_running_loop()
            await _collect(loop, 3.0)

        asyncio.run(scenario())

    assert not [r for r in caplog.records if "event loop stalled" in r.getMessage()]
