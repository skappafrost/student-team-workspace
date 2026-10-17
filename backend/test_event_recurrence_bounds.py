"""Bounds on recurring-event expansion (routers/events.py).

A calendar-list range is walked occurrence by occurrence, from the event's own
``start_at`` up to the requested end. Before these bounds the loop stopped only
on ``cap`` — a count of *rows appended* — so a range far from the event's anchor
skipped millions of dates without ever approaching it. Measured by hand on the
unbounded code: one daily event with a year-9999 window spent 2,912,442 steps to
produce 1 row, five of them 14,562,210; the weekly shape of the same window
walked past ``datetime.max`` and answered 500.

Assertions are on **step counts**, never wall time: a loaded machine makes a
duration claim meaningless, so the instrument is the seam the fix runs through —
``_next_occurrence`` is called exactly once per iteration, and ``step_counter``
counts those calls.

Every assertion that could pass for the wrong reason carries its control here:
the calibrations pin the counter to a hand-computable case, the near-window
requests pin the rows, and the unit-level calls pin the paths that the endpoint's
own range guard would otherwise short-circuit.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

import routers.events as events_mod
from app import app
from models import Event
from routers.events import (
    MAX_EXPANSION_RANGE,
    MAX_EXPANSION_STEPS,
    _add_months,
    _expand_occurrences,
    _next_occurrence,
)

#: Steps the unbounded code spent on one daily event with a year-9999 window.
#: Kept as a number because the ceiling assertion on ``MAX_EXPANSION_STEPS`` is
#: meaningless without the thing it has to be small compared to.
MEASURED_UNBOUNDED_STEPS = 2_912_442

ROW_CAP = 200


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def ws_id(workspace_factory):
    return workspace_factory("owner", name="Recurrence Bounds", slug="recurrence-bounds")["id"]


@pytest.fixture
def step_counter(monkeypatch):
    """Count expansion iterations, exactly one count per loop step.

    Wrapping ``_next_occurrence`` measures work rather than payload: a skipped
    date calls it just as an appended one does. The wrapper returns the real
    value, so the walk itself is untouched.
    """
    real = events_mod._next_occurrence
    counter = {"steps": 0}

    def counting(current, recurrence):
        counter["steps"] += 1
        return real(current, recurrence)

    monkeypatch.setattr(events_mod, "_next_occurrence", counting)
    return counter


def _create(client, ws_id, title, start_at, recurrence="daily"):
    resp = client.post(
        f"/workspaces/{ws_id}/events",
        json={"title": title, "start_at": start_at.isoformat(), "recurrence": recurrence},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _list(client, ws_id, start, end, counter):
    """One ranged list request, with the step counter zeroed for it alone."""
    counter["steps"] = 0
    return client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": start.isoformat(), "end": end.isoformat()},
    )


def _rows(resp, title):
    return [e for e in resp.json() if e["title"] == title]


def predicted_daily_steps(start_at, range_end):
    """Iterations a daily walk runs before its date passes ``range_end``.

    One per day, the anchor's own day included — the formula the first control
    checks against a hand-countable case.
    """
    return (range_end - start_at).days + 1


def _mk_event(recurrence="daily", start=None, end=None):
    """An unsaved Event: ``_expand_occurrences`` needs a row, not a request."""
    base = start or dt.datetime(2026, 9, 1, 9, 0)
    return Event(
        id="evt-1",
        workspace_id="ws-1",
        title="X",
        start_at=base,
        end_at=end,
        all_day=False,
        event_type="meeting",
        recurrence=recurrence,
        created_by="owner",
        created_at=base,
        updated_at=base,
    )


# ---------------------------------------------------------------------------
# Controls — the instrument and the rows both have to be right
# ---------------------------------------------------------------------------


def test_control_step_counter_matches_a_hand_computed_month(client, ws_id, step_counter):
    """2026-01-01 09:00 daily over 2026-01-01..2026-01-31 = 30 steps, 30 rows.

    Hand-predicted from the loop shape: the window ends at midnight on the 31st
    while the event fires at 09:00, so 01-30 09:00 is the last date satisfying
    ``start_at <= end``. This calibrates the counter and the predictor together,
    which is what makes every step assertion below load-bearing.
    """
    anchor = dt.datetime(2026, 1, 1, 9, 0)
    _create(client, ws_id, "standup", anchor)
    resp = _list(client, ws_id, dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 31), step_counter)

    assert resp.status_code == 200, resp.text
    predicted = predicted_daily_steps(anchor, dt.datetime(2026, 1, 31))
    assert step_counter["steps"] == predicted == 30
    assert len(_rows(resp, "standup")) == 30


def test_control_rows_are_unchanged_for_normal_requests(client, ws_id, step_counter):
    """Legitimate expansion still returns the same occurrences, dates and all.

    The expectations are literal dates, not counts, so a bound that silently
    drops or shifts an occurrence fails here instead of showing up as a smaller
    step number somewhere else. One event is live per request — a workspace's
    recurring events all expand against the same range, so a shared workspace
    would fold their steps together and make the count meaningless.
    """

    def control(title, recurrence, anchor, window_start, window_end, expected, steps):
        event = _create(client, ws_id, title, anchor, recurrence)
        resp = _list(client, ws_id, window_start, window_end, step_counter)
        try:
            assert resp.status_code == 200, resp.text
            assert [o["start_at"] for o in _rows(resp, title)] == expected
            assert step_counter["steps"] == steps, f"{recurrence}: {step_counter['steps']}"
        finally:
            assert client.delete(f"/events/{event['id']}").status_code == 204

    control(
        "standup",
        "daily",
        dt.datetime(2026, 9, 3, 9, 0),
        dt.datetime(2026, 9, 3),
        dt.datetime(2026, 9, 6, 23, 59, 59),
        [
            "2026-09-03T09:00:00",
            "2026-09-04T09:00:00",
            "2026-09-05T09:00:00",
            "2026-09-06T09:00:00",
        ],
        4,
    )
    control(
        "sync",
        "weekly",
        dt.datetime(2026, 9, 1, 10, 0),
        dt.datetime(2026, 9, 1),
        dt.datetime(2026, 9, 30, 23, 59, 59),
        [
            "2026-09-01T10:00:00",
            "2026-09-08T10:00:00",
            "2026-09-15T10:00:00",
            "2026-09-22T10:00:00",
            "2026-09-29T10:00:00",
        ],
        5,
    )
    # Month-end clamping is unchanged too: Jan 31 walks 28ths and stays there.
    control(
        "review",
        "monthly",
        dt.datetime(2026, 1, 31, 9, 0),
        dt.datetime(2026, 1, 1),
        dt.datetime(2026, 4, 30, 23, 59, 59),
        [
            "2026-01-31T09:00:00",
            "2026-02-28T09:00:00",
            "2026-03-28T09:00:00",
            "2026-04-28T09:00:00",
        ],
        4,
    )


def test_occurrence_ids_and_wire_format_survive_the_bounds(client, ws_id, step_counter):
    """The occurrence_id pairing and the naive-UTC wire form are unchanged.

    Naive UTC is a cross-dialect contract (see schemas.py and
    test_dialect_parity.py): stripping the offset is what lets SQLite and
    Postgres serialize the same string, so a bound that reintroduced an offset
    or a ``Z`` would fail here on the request path it is most likely to touch.
    """
    event = _create(client, ws_id, "standup", dt.datetime(2026, 9, 3, 9, 0), "daily")
    resp = _list(
        client, ws_id, dt.datetime(2026, 9, 3), dt.datetime(2026, 9, 4, 23, 59, 59), step_counter
    )
    occ = _rows(resp, "standup")
    assert [o["occurrence_id"] for o in occ] == [
        f"{event['id']}@2026-09-0{n}" for n in (3, 4)
    ]
    assert all("Z" not in o["start_at"] and "+" not in o["start_at"] for o in occ)
    assert occ[0]["start_at"] == "2026-09-03T09:00:00"


# ---------------------------------------------------------------------------
# The step bound: work, not payload
# ---------------------------------------------------------------------------


def test_far_future_window_walks_the_step_bound_not_the_whole_range(
    client, ws_id, step_counter
):
    """Daily 2026 event, one-day window in 9999: bounded steps, empty payload.

    The span is a single day, so the endpoint's range guard cannot be what
    stopped this — only the step bound can, which is why the assertion is on the
    step count and not the status code. The unbounded code took 2,912,442 steps
    here and returned 1 row.
    """
    anchor = dt.datetime(2026, 1, 1, 9, 0)
    _create(client, ws_id, "standup", anchor)
    resp = _list(client, ws_id, dt.datetime(9999, 12, 30), dt.datetime(9999, 12, 31), step_counter)

    assert resp.status_code == 200, resp.text
    assert step_counter["steps"] == MAX_EXPANSION_STEPS < MEASURED_UNBOUNDED_STEPS
    # Truncation is the price of the bound: the year-9999 occurrence is no
    # longer reachable, so the range that needs it answers empty instead of slow.
    assert _rows(resp, "standup") == []


def test_step_bound_leaves_a_reachable_deep_window_alone(client, ws_id, step_counter):
    """Control for the truncation above: the same one-day shape nineteen steps
    inside the bound still walks to its occurrence and returns it."""
    anchor = dt.datetime(2026, 1, 1, 9, 0)
    _create(client, ws_id, "standup", anchor)
    window = anchor + dt.timedelta(days=MAX_EXPANSION_STEPS - 19)
    resp = _list(client, ws_id, window, window, step_counter)

    assert resp.status_code == 200, resp.text
    predicted = predicted_daily_steps(anchor, window)
    assert step_counter["steps"] == predicted < MAX_EXPANSION_STEPS
    assert [o["start_at"] for o in _rows(resp, "standup")] == [window.isoformat()]


def test_cap_still_bounds_rows_independently_of_the_step_bound(client, ws_id, step_counter):
    """Opening the range at the event's own start makes every iteration append,
    so the row cap ends the walk long before the step bound is anywhere near."""
    _create(client, ws_id, "standup", dt.datetime(2026, 1, 1, 9, 0))
    resp = _list(client, ws_id, dt.datetime(2026, 1, 1), dt.datetime(2026, 12, 31), step_counter)

    assert resp.status_code == 200, resp.text
    assert len(_rows(resp, "standup")) == ROW_CAP
    assert step_counter["steps"] == ROW_CAP < MAX_EXPANSION_STEPS


def test_the_two_bounds_bind_independently_at_unit_level(step_counter):
    """Direct calls skip the endpoint's range guard, which is how each bound gets
    exercised with the other one provably not responsible."""
    event = _mk_event("daily", start=dt.datetime(2026, 9, 1, 9, 0))

    step_counter["steps"] = 0
    rows = _expand_occurrences(event, dt.datetime(2026, 1, 1), dt.datetime(2036, 1, 1))
    assert len(rows) == ROW_CAP, "every step appends, so the row cap binds first"
    assert step_counter["steps"] == ROW_CAP

    step_counter["steps"] = 0
    rows = _expand_occurrences(event, dt.datetime(2090, 1, 1), dt.datetime(2090, 1, 2))
    assert rows == [], "19,000+ skipped steps never approach the row cap"
    assert step_counter["steps"] == MAX_EXPANSION_STEPS

    # Control for both: the same call shape on a reachable range.
    step_counter["steps"] = 0
    rows = _expand_occurrences(event, dt.datetime(2026, 9, 1), dt.datetime(2026, 9, 5, 23, 59))
    assert [o.start_at for o in rows] == [
        dt.datetime(2026, 9, day, 9, 0) for day in (1, 2, 3, 4, 5)
    ]
    assert step_counter["steps"] == 5


# ---------------------------------------------------------------------------
# The range guard: 400 at the boundary, not a 500 or a slow 200
# ---------------------------------------------------------------------------


def test_range_wider_than_the_horizon_is_a_client_error(client, ws_id, step_counter):
    """2026..9999 is refused before any event is expanded."""
    _create(client, ws_id, "standup", dt.datetime(2026, 1, 1, 9, 0))
    resp = _list(client, ws_id, dt.datetime(2026, 1, 1), dt.datetime(9999, 12, 31), step_counter)

    assert resp.status_code == 400, resp.text
    assert str(MAX_EXPANSION_RANGE.days) in resp.json()["detail"]
    assert step_counter["steps"] == 0, "the boundary rejects; it does not truncate"


def test_horizon_accepts_its_last_day_and_refuses_the_next(client, ws_id, step_counter):
    """Two requests one day apart: the limit is exactly where it is claimed."""
    _create(client, ws_id, "standup", dt.datetime(2026, 1, 1, 9, 0))
    window_start = dt.datetime(2026, 1, 1)

    resp = _list(client, ws_id, window_start, window_start + MAX_EXPANSION_RANGE, step_counter)
    assert resp.status_code == 200, resp.text
    assert len(_rows(resp, "standup")) == ROW_CAP and step_counter["steps"] == ROW_CAP

    resp = _list(
        client,
        ws_id,
        window_start,
        window_start + MAX_EXPANSION_RANGE + dt.timedelta(days=1),
        step_counter,
    )
    assert resp.status_code == 400, resp.text
    assert str(MAX_EXPANSION_RANGE.days) in resp.json()["detail"]
    assert step_counter["steps"] == 0


def test_weekly_far_future_range_no_longer_answers_500(client, ws_id, step_counter):
    """The measured crash: a weekly event with a year-9999 range answered 500.

    Both shapes of it are covered, by different mechanisms — the wide range is
    refused at the boundary, the narrow year-9999 one is bounded by steps and
    stops stepping centuries short of ``datetime.max``. The quiet client is
    deliberate: it reports a server-side exception as a 500 status instead of
    raising, so a regression shows up as the status code the probe recorded.
    """
    _create(client, ws_id, "sync", dt.datetime(2026, 1, 5, 9, 0), "weekly")
    quiet = TestClient(app, raise_server_exceptions=False)
    quiet.headers["Authorization"] = client.headers["Authorization"]

    wide = quiet.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "2026-01-01T00:00:00", "end": "9999-12-31T00:00:00"},
    )
    assert wide.status_code == 400, wide.text
    assert str(MAX_EXPANSION_RANGE.days) in wide.json()["detail"]

    step_counter["steps"] = 0
    narrow = quiet.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "9999-12-30T00:00:00", "end": "9999-12-31T00:00:00"},
    )
    assert narrow.status_code == 200, narrow.text
    assert narrow.json() == []
    # Weekly steps 7 days at a time: the bound stops the walk around year 2410,
    # which is what makes the old OverflowError unreachable from this shape.
    assert step_counter["steps"] == MAX_EXPANSION_STEPS


def test_event_anchored_at_the_end_of_the_calendar_does_not_crash(client, ws_id, step_counter):
    """The path neither bound covers: the anchor itself is in year 9999.

    The request is well inside the horizon and the walk is nowhere near the step
    bound — the very first step is the one that would leave the representable
    range. It used to raise ``OverflowError`` (daily/weekly) and ``ValueError``
    (the monthly ``replace``); all three are one-row 200s now, and each anchor's
    normalization to naive UTC happens before the limit is compared, which is the
    timestamptz case CI's backend-pg job runs.
    """
    _create(client, ws_id, "daily-9999", dt.datetime(9999, 12, 31, 9, 0), "daily")
    _create(client, ws_id, "weekly-9999", dt.datetime(9999, 12, 27, 9, 0), "weekly")
    _create(client, ws_id, "monthly-9999", dt.datetime(9999, 12, 15, 9, 0), "monthly")

    resp = _list(
        client,
        ws_id,
        dt.datetime(9999, 12, 1),
        dt.datetime(9999, 12, 31, 23, 59, 59),
        step_counter,
    )
    assert resp.status_code == 200, resp.text
    assert {t: [o["start_at"] for o in _rows(resp, t)] for t in
            ("daily-9999", "weekly-9999", "monthly-9999")} == {
        "daily-9999": ["9999-12-31T09:00:00"],
        "weekly-9999": ["9999-12-27T09:00:00"],
        "monthly-9999": ["9999-12-15T09:00:00"],
    }
    assert step_counter["steps"] == 3, "one step each, and each hit the calendar limit"


# ---------------------------------------------------------------------------
# The step function itself
# ---------------------------------------------------------------------------


def test_next_occurrence_stops_exactly_at_the_calendar_limit():
    """The last legal step still steps; the first illegal one returns None."""
    assert _next_occurrence(dt.datetime(9999, 12, 30, 9, 0), "daily") == dt.datetime(
        9999, 12, 31, 9, 0
    )
    assert _next_occurrence(dt.datetime(9999, 12, 31, 9, 0), "daily") is None

    # 9999-12-24 is the last weekly anchor whose +7 days still fits.
    assert _next_occurrence(dt.datetime(9999, 12, 24, 9, 0), "weekly") == dt.datetime(
        9999, 12, 31, 9, 0
    )
    assert _next_occurrence(dt.datetime(9999, 12, 25, 9, 0), "weekly") is None


def test_next_occurrence_monthly_stops_after_the_last_december():
    assert _next_occurrence(dt.datetime(9999, 11, 15, 9, 0), "monthly") == dt.datetime(
        9999, 12, 15, 9, 0
    )
    assert _next_occurrence(dt.datetime(9999, 12, 15, 9, 0), "monthly") is None
    # Month-end clamping is why _add_months exists; the bound left it alone.
    assert _next_occurrence(dt.datetime(2026, 1, 31, 9, 0), "monthly") == _add_months(
        dt.datetime(2026, 1, 31, 9, 0), 1
    ) == dt.datetime(2026, 2, 28, 9, 0)


def test_next_occurrence_keeps_the_old_fallback_dispatch():
    """``recurrence`` is a free-text column; anything unrecognized still steps monthly."""
    assert _next_occurrence(dt.datetime(2026, 1, 31, 9, 0), "yearly") == dt.datetime(
        2026, 2, 28, 9, 0
    )


def test_step_bound_leaves_headroom_and_stays_far_below_the_measured_burn():
    """Where the constants sit relative to real use and to the measured work.

    Five times the widest legitimate daily walk (``MAX_EXPANSION_RANGE`` of daily
    occurrences is ~1,830 steps) at the bottom, a fraction of the 2.9M-step walk
    that was measured costing seconds at the top, and far away from the row cap
    so nobody can read one bound as the other.
    """
    widest_legitimate_daily_walk = MAX_EXPANSION_RANGE.days
    assert widest_legitimate_daily_walk * 5 <= MAX_EXPANSION_STEPS
    assert MAX_EXPANSION_STEPS <= MEASURED_UNBOUNDED_STEPS // 25
    assert ROW_CAP * 50 < MAX_EXPANSION_STEPS
    assert MAX_EXPANSION_RANGE >= dt.timedelta(days=365 * 5)
