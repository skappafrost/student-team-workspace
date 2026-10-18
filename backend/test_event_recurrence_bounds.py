"""Bounds on recurring-event expansion (routers/events.py).

A calendar-list range is walked occurrence by occurrence and stopped at the
requested end. Before these bounds the loop stopped only on ``cap`` — a count of
*rows appended* — so a range far from the event's anchor skipped millions of
dates without ever approaching it. Measured by hand on the unbounded code: one
daily event with a year-9999 window spent 2,912,442 steps to produce 1 row, five
of them 14,562,210; the weekly shape of the same window walked past
``datetime.max`` and answered 500, as did an event long enough for its own
duration to do the same one step in.

The walk now starts at the first occurrence that can still reach the range
instead of at the event's anchor, so a range costs one step per occurrence inside
it and the rows it returns do not depend on how old the event is. Bounding the
anchor's own history instead would have answered legitimate windows short — which
is why the exactness tests below compare the seeded walk against an anchor walk
date for date, and why the step bound is asserted to be a backstop: a truncated
response and a complete one both arrive as a 200.

Assertions are on **step counts**, never wall time: a loaded machine makes a
duration claim meaningless. The instrument counts calls to ``_next_occurrence``,
which is one per loop iteration only while the loop calls it once and nothing else
does — ``test_counter_counts_loop_iterations_not_anchor_distance`` pins that by
asking for the same one-day window at three distances from the anchor, where a
seed that walked toward its window would make the far one cost thousands.

Every assertion that could pass for the wrong reason carries its control here:
the calibrations pin the counter to a hand-computable case, the near-window
requests pin the rows, and the unit-level calls pin the paths that the endpoint's
own range guard would otherwise short-circuit.
"""

import datetime as dt
import inspect
from pathlib import Path

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
    _monthly_at,
    _naive_utc,
    _next_occurrence,
    _occurrence_end,
)

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "API.md"

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
    """Count calls to ``_next_occurrence`` — one per loop iteration, while that holds.

    Wrapping the step function counts loop iterations rather than payload: a skipped
    date calls it just as an appended one does. It is not a census of the work the
    request does — a monthly walk probes up to 400 months inside ``_monthly_at``
    without calling the step function at all. The wrapper returns the real value, so
    the walk itself is untouched. The relationship is not self-evident and the
    seed is a second site where a step call could hide, so
    ``test_counter_counts_loop_iterations_not_anchor_distance`` pins it and
    ``test_control_step_counter_matches_a_hand_computed_month`` pins it again at
    the anchor end.
    """
    real = events_mod._next_occurrence
    counter = {"steps": 0}

    def counting(current, recurrence):
        counter["steps"] += 1
        return real(current, recurrence)

    monkeypatch.setattr(events_mod, "_next_occurrence", counting)
    return counter


@pytest.fixture()
def one_event(client, ws_id):
    """Create events for a test and delete them in fixture teardown.

    The teardown assertion belongs here rather than in a ``finally`` around the
    test body: a cleanup check that raises from inside ``finally`` replaces the
    exception it was standing behind, so a genuine row or step regression would
    be reported as a delete failure.
    """
    created: list[str] = []

    def add(title, anchor, recurrence="daily", end_at=None):
        event = _create(client, ws_id, title, anchor, recurrence, end_at)
        created.append(event["id"])
        return event

    yield add

    for event_id in created:
        assert client.delete(f"/events/{event_id}").status_code == 204


@pytest.fixture()
def quiet_client(client):
    """The same app and identity, but a server-side exception answers `500`.

    The crash these tests replaced reached the caller as an HTTP 500; the plain
    client re-raises instead, which would report a broken test rather than the
    symptom being guarded against.
    """
    quiet = TestClient(app, raise_server_exceptions=False)
    quiet.headers["Authorization"] = client.headers["Authorization"]
    return quiet


def _create(client, ws_id, title, start_at, recurrence="daily", end_at=None):
    resp = client.post(
        f"/workspaces/{ws_id}/events",
        json={
            "title": title,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat() if end_at else None,
            "recurrence": recurrence,
        },
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


def anchor_walk(event, range_start, range_end, cap=ROW_CAP):
    """The start dates the *un-seeded* walk would produce for the same request.

    This is the pre-fix shape — begin at the event's own ``start_at``, apply the
    same keep rule, stop only at the range end and the row cap, no step bound. It
    reproduces the date arithmetic through the module's own step helpers (bound to
    their originals by this file's imports, so the counting fixture cannot pollute
    it) and restates the window filter in the open, which is what makes it an
    independent answer to compare against: reaching a window is not the same as
    answering it.
    """
    start = _naive_utc(event.start_at)
    end = _naive_utc(event.end_at) if event.end_at else None
    duration = (end - start) if end else None
    rs, re_ = _naive_utc(range_start), _naive_utc(range_end)
    out: list[dt.datetime] = []
    current: dt.datetime | None = start
    while current is not None and current <= re_ and len(out) < cap:
        occ_end = _occurrence_end(current, duration)
        if (occ_end is None or occ_end >= rs) and current >= rs or (
            current < rs and occ_end is not None and occ_end >= rs
        ):
            out.append(current)
        current = _next_occurrence(current, event.recurrence)
    return out


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


def test_counter_counts_loop_iterations_not_anchor_distance(step_counter):
    """The same one-day window at three distances counts the same number of steps.

    ``step_counter`` wraps ``_next_occurrence``, so it measures iterations only
    while nothing else calls that function, and seeding is the one site that could:
    a seed that walked toward its window instead of computing it would count tens
    of thousands of calls at 50,000 days out and one at the anchor. Equal counts at
    unequal distances are what say the number is the loop's, and monthly is the
    shape with a loop inside the seed's own arithmetic, so it is pinned too.
    """
    anchor = dt.datetime(2026, 9, 1, 9, 0)
    daily = _mk_event("daily", start=anchor)
    for days_out in (0, 400, 50_000):
        window = anchor + dt.timedelta(days=days_out)
        step_counter["steps"] = 0
        rows = _expand_occurrences(daily, window, window + dt.timedelta(hours=3))
        assert [o.start_at for o in rows] == [window], f"{days_out} days out"
        assert step_counter["steps"] == 1, f"{days_out} days out"

    monthly_anchor = dt.datetime(2026, 1, 31, 9, 0)
    monthly = _mk_event("monthly", start=monthly_anchor)
    # A window at the anchor itself has no earlier month to start in, so the walk
    # is the one step that appends; 40 and 20,000 months out both start one month
    # early and take a second.
    for months_out, expected_steps in ((0, 1), (40, 2), (20_000, 2)):
        window_start = _add_months(monthly_anchor, months_out).replace(day=1)
        window_end = window_start + dt.timedelta(days=40)
        step_counter["steps"] = 0
        rows = _expand_occurrences(monthly, window_start, window_end)
        assert [o.start_at for o in rows] == [_monthly_at(monthly_anchor, months_out)], (
            f"{months_out} months out"
        )
        assert step_counter["steps"] == expected_steps, f"{months_out} months out"


#: (title, recurrence, anchor, window, expected occurrence starts, loop steps).
#: The step counts are hand-derived from the loop shape: the seed lands at most
#: one period before the first row, and every later step appends until the window
#: is passed.
NORMAL_REQUESTS = [
    pytest.param(
        "standup",
        "daily",
        dt.datetime(2026, 9, 3, 9, 0),
        (dt.datetime(2026, 9, 3), dt.datetime(2026, 9, 6, 23, 59, 59)),
        [
            "2026-09-03T09:00:00",
            "2026-09-04T09:00:00",
            "2026-09-05T09:00:00",
            "2026-09-06T09:00:00",
        ],
        4,
        id="daily-at-the-anchor",
    ),
    pytest.param(
        "standup",
        "daily",
        dt.datetime(2026, 1, 1, 9, 0),
        (dt.datetime(2026, 9, 1), dt.datetime(2026, 9, 3, 23, 59, 59)),
        [
            "2026-09-01T09:00:00",
            "2026-09-02T09:00:00",
            "2026-09-03T09:00:00",
        ],
        4,
        id="daily-window-past-the-anchor",
    ),
    pytest.param(
        "sync",
        "weekly",
        dt.datetime(2026, 9, 1, 10, 0),
        (dt.datetime(2026, 9, 1), dt.datetime(2026, 9, 30, 23, 59, 59)),
        [
            "2026-09-01T10:00:00",
            "2026-09-08T10:00:00",
            "2026-09-15T10:00:00",
            "2026-09-22T10:00:00",
            "2026-09-29T10:00:00",
        ],
        5,
        id="weekly",
    ),
    pytest.param(
        "review",
        "monthly",
        dt.datetime(2026, 1, 31, 9, 0),
        (dt.datetime(2026, 1, 1), dt.datetime(2026, 4, 30, 23, 59, 59)),
        [
            "2026-01-31T09:00:00",
            "2026-02-28T09:00:00",
            "2026-03-28T09:00:00",
            "2026-04-28T09:00:00",
        ],
        4,
        id="monthly-clamping-at-the-anchor",
    ),
    pytest.param(
        "review",
        "monthly",
        dt.datetime(2026, 1, 31, 9, 0),
        (dt.datetime(2032, 2, 1), dt.datetime(2032, 2, 29, 23, 59, 59)),
        # The anchor sequence reached February on a 28-day month and stays clamped:
        # the seed has to land on that sequence, not on the 31st-of-January it
        # computes from, or this month answers a date no near window ever returns.
        ["2032-02-28T09:00:00"],
        2,
        id="monthly-clamping-past-the-anchor",
    ),
]


@pytest.mark.parametrize(
    ("title", "recurrence", "anchor", "window", "expected", "steps"), NORMAL_REQUESTS
)
def test_control_rows_are_unchanged_for_normal_requests(
    client, ws_id, one_event, step_counter, title, recurrence, anchor, window, expected, steps
):
    """Legitimate expansion still returns the same occurrences, dates and all.

    The expectations are literal dates, not counts, so a bound that silently
    drops or shifts an occurrence fails here instead of showing up as a smaller
    step number somewhere else. One event is live per case — a workspace's
    recurring events all expand against the same range, so a shared run would
    fold their steps together and make the count meaningless — and it is deleted
    by ``one_event``'s teardown, after the assertions rather than instead of them.
    """
    one_event(title, anchor, recurrence)
    resp = _list(client, ws_id, window[0], window[1], step_counter)

    assert resp.status_code == 200, resp.text
    assert [o["start_at"] for o in _rows(resp, title)] == expected
    assert step_counter["steps"] == steps


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
# Exactness: a window is answered whatever its distance from the anchor
# ---------------------------------------------------------------------------


def test_year_9999_one_day_window_returns_its_single_row(client, ws_id, step_counter):
    """Daily 2026 event, one-day window in 9999: that row, in two steps.

    The unbounded code spent 2,912,442 steps on this row, and a walk capped at
    20,000 steps from a 2026 anchor runs out about 55 years out — centuries short
    of the window, answering 200 with an empty body for a range that does contain
    an occurrence. The span here is one day, so the endpoint's range guard is not
    what ends the walk either; the seed computes the period that reaches it.
    """
    anchor = dt.datetime(2026, 1, 1, 9, 0)
    _create(client, ws_id, "standup", anchor)
    resp = _list(client, ws_id, dt.datetime(9999, 12, 30), dt.datetime(9999, 12, 31), step_counter)

    assert resp.status_code == 200, resp.text
    # The window closes at midnight on the 31st while the event fires at 09:00, so
    # one row is the whole correct answer rather than a fragment of a longer one.
    assert [o["start_at"] for o in _rows(resp, "standup")] == ["9999-12-30T09:00:00"]
    assert step_counter["steps"] == 2 < MAX_EXPANSION_STEPS < MEASURED_UNBOUNDED_STEPS


def test_partial_month_far_from_the_anchor_comes_back_complete(client, ws_id, step_counter):
    """Two December-to-October 2080 months against a 2026-01-01 daily anchor, whole.

    Both windows sit at the edge of the reach a 20,000-step bound bought from that
    anchor, which is where the bound answered instead of the calendar. December 2080
    opens 20,057 days out, so the walk ran out before it began and the month came
    back empty; the month before it straddles the limit, and its first 14 days came
    back with the rest missing — no flag, no error, completeness decided by how old
    the event was rather than by the payload. A month of hits is a month of steps
    now, wherever it falls.
    """
    anchor = dt.datetime(2026, 1, 1, 9, 0)
    _create(client, ws_id, "standup", anchor)

    resp = _list(
        client,
        ws_id,
        dt.datetime(2080, 12, 1),
        dt.datetime(2080, 12, 31, 23, 59, 59),
        step_counter,
    )
    assert resp.status_code == 200, resp.text
    assert [o["start_at"] for o in _rows(resp, "standup")] == [
        f"2080-12-{day:02d}T09:00:00" for day in range(1, 32)
    ]
    assert step_counter["steps"] == 32 < MAX_EXPANSION_STEPS, "31 hits plus the seeded period"

    resp = _list(
        client,
        ws_id,
        dt.datetime(2080, 9, 20),
        dt.datetime(2080, 10, 19, 23, 59, 59),
        step_counter,
    )
    assert resp.status_code == 200, resp.text
    # The 30 consecutive firings from 2080-09-20 to 2080-10-19, across a month end.
    assert [o["start_at"] for o in _rows(resp, "standup")] == [
        (dt.datetime(2080, 9, 20, 9, 0) + dt.timedelta(days=day)).isoformat()
        for day in range(30)
    ]
    assert step_counter["steps"] == 31 < MAX_EXPANSION_STEPS


def test_a_window_past_the_old_walk_depth_is_answered_like_a_near_one(
    client, ws_id, step_counter
):
    """One-day windows 19,981 and 40,000 days past the anchor both return their row.

    The distance the step bound used to cap a walk at now sits in the middle of the
    reachable range: the skip decides where the walk begins, so distance buys
    neither extra work nor missing rows.
    """
    anchor = dt.datetime(2026, 1, 1, 9, 0)
    _create(client, ws_id, "standup", anchor)

    for days_out in (MAX_EXPANSION_STEPS - 19, MAX_EXPANSION_STEPS * 2):
        window = anchor + dt.timedelta(days=days_out)
        resp = _list(client, ws_id, window, window, step_counter)

        assert resp.status_code == 200, resp.text
        assert [o["start_at"] for o in _rows(resp, "standup")] == [window.isoformat()]
        assert step_counter["steps"] == 1, f"{days_out} days out"


def test_the_seed_returns_exactly_what_an_anchor_walk_would():
    """The same rows for windows the step bound used to cut off.

    Distances stay inside a few thousand periods so the reference walk finishes
    inside a test run; the shape of the claim is the same at year 9999, where the
    two tests above pin the rows literally. Each case carries the row count it has
    to produce as well, because a bare comparison would also pass if both walks
    came back empty.
    """
    cases = [
        # (recurrence, anchor, duration, window, rows)
        (
            "daily",
            dt.datetime(2026, 1, 1, 9, 0),
            None,
            (dt.datetime(2026, 11, 1), dt.datetime(2026, 11, 30, 23, 59, 59)),
            30,
        ),
        (
            "daily",
            dt.datetime(2026, 1, 1, 9, 0),
            dt.timedelta(hours=2),
            (dt.datetime(2031, 6, 1), dt.datetime(2031, 6, 5)),
            4,
        ),
        (
            "daily",
            dt.datetime(2026, 9, 1, 9, 0),
            None,
            (dt.datetime(2039, 10, 1), dt.datetime(2039, 10, 2)),
            1,
        ),
        (
            "weekly",
            dt.datetime(2026, 1, 5, 9, 0),
            None,
            (dt.datetime(2030, 3, 1), dt.datetime(2030, 4, 30, 23, 59, 59)),
            9,
        ),
        (
            # A window with nothing in it has to stay empty for the right reason.
            "weekly",
            dt.datetime(2026, 1, 5, 9, 0),
            dt.timedelta(hours=1, minutes=30),
            (dt.datetime(2035, 12, 26), dt.datetime(2035, 12, 27)),
            0,
        ),
        (
            # Month-end anchors clamp and stay clamped, at the anchor and far from it.
            "monthly",
            dt.datetime(2026, 1, 31, 9, 0),
            None,
            (dt.datetime(2032, 2, 1), dt.datetime(2032, 2, 29, 23, 59, 59)),
            1,
        ),
        (
            "monthly",
            dt.datetime(2026, 1, 31, 9, 0),
            dt.timedelta(hours=4),
            (dt.datetime(2040, 2, 27), dt.datetime(2040, 3, 2, 12, 0)),
            1,
        ),
        (
            "monthly",
            dt.datetime(2026, 1, 31, 9, 0),
            None,
            (dt.datetime(2080, 2, 1), dt.datetime(2080, 2, 29, 23, 59, 59)),
            1,
        ),
    ]

    for recurrence, anchor, duration, (window_start, window_end), expected_rows in cases:
        event = _mk_event(recurrence, start=anchor, end=anchor + duration if duration else None)
        got = [o.start_at for o in _expand_occurrences(event, window_start, window_end)]

        assert len(got) == expected_rows, f"{recurrence} {window_start:%Y-%m-%d}"
        assert got == anchor_walk(event, window_start, window_end), recurrence


def test_cap_still_bounds_rows_independently_of_the_step_bound(client, ws_id, step_counter):
    """Opening the range at the event's own start makes every iteration append,
    so the row cap ends the walk long before the step bound is anywhere near."""
    _create(client, ws_id, "standup", dt.datetime(2026, 1, 1, 9, 0))
    resp = _list(client, ws_id, dt.datetime(2026, 1, 1), dt.datetime(2026, 12, 31), step_counter)

    assert resp.status_code == 200, resp.text
    assert len(_rows(resp, "standup")) == ROW_CAP
    assert step_counter["steps"] == ROW_CAP < MAX_EXPANSION_STEPS


def test_the_step_bound_is_a_backstop_that_still_ends_a_walk(step_counter):
    """With ``cap`` raised past it, the step ceiling still stops the loop.

    The seed makes a walk cost one step per occurrence inside its own window, so
    reaching the ceiling takes a range wider than 20,000 periods — well past the
    1,830 days the endpoint admits, which is why no accepted request loses rows to
    it. When it does bind it still answers 200 with the rest of the range missing,
    which is the failure mode the tests above exist to prevent.
    """
    event = _mk_event("daily", start=dt.datetime(2026, 9, 1, 9, 0))
    step_counter["steps"] = 0
    rows = _expand_occurrences(
        event,
        dt.datetime(2026, 9, 1),
        dt.datetime(2026, 9, 1) + dt.timedelta(days=40_000),
        cap=MAX_EXPANSION_STEPS * 2,
    )

    assert step_counter["steps"] == MAX_EXPANSION_STEPS
    assert len(rows) == MAX_EXPANSION_STEPS, "every step appends, so rows track steps here"


def test_the_two_bounds_bind_independently_at_unit_level(step_counter):
    """Direct calls skip the endpoint's range guard, which is how each bound gets
    exercised with the other one provably not responsible."""
    event = _mk_event("daily", start=dt.datetime(2026, 9, 1, 9, 0))

    # A window opened before the anchor has nothing to skip and every step appends,
    # so the row cap ends the walk with the step bound nowhere near.
    step_counter["steps"] = 0
    rows = _expand_occurrences(event, dt.datetime(2026, 1, 1), dt.datetime(2036, 1, 1))
    assert len(rows) == ROW_CAP, "every step appends, so the row cap binds first"
    assert step_counter["steps"] == ROW_CAP

    # The same request 63 years past the anchor: two steps, one row, and the row
    # cap nowhere near involved.
    step_counter["steps"] = 0
    rows = _expand_occurrences(event, dt.datetime(2090, 1, 1), dt.datetime(2090, 1, 2))
    assert [o.start_at for o in rows] == [dt.datetime(2090, 1, 1, 9, 0)]
    assert step_counter["steps"] == 2

    # Control for both: the same call shape on a window at the anchor.
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


def test_weekly_far_future_range_no_longer_answers_500(ws_id, quiet_client, step_counter):
    """The measured crash: a weekly event with a year-9999 range answered 500.

    Both shapes of it are covered, by different mechanisms — the wide range is
    refused at the boundary, and the narrow year-9999 one seeds itself a week from
    the end of the calendar, where ``_next_occurrence`` ends the walk instead of
    stepping past ``datetime.max``. One counted step says the step bound is not
    what keeps that shape off the crash path.
    """
    _create(quiet_client, ws_id, "sync", dt.datetime(2026, 1, 5, 9, 0), "weekly")

    wide = quiet_client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "2026-01-01T00:00:00", "end": "9999-12-31T00:00:00"},
    )
    assert wide.status_code == 400, wide.text
    assert str(MAX_EXPANSION_RANGE.days) in wide.json()["detail"]

    step_counter["steps"] = 0
    narrow = quiet_client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "9999-12-30T00:00:00", "end": "9999-12-31T00:00:00"},
    )
    assert narrow.status_code == 200, narrow.text
    # The series steps through 9999-12-27 and its next date is not representable,
    # so this window genuinely holds no occurrence — empty because it is empty, not
    # because the walk fell short, which the adjacent window below is the control for.
    assert narrow.json() == []
    assert step_counter["steps"] == 1

    step_counter["steps"] = 0
    hit = quiet_client.get(
        f"/workspaces/{ws_id}/events",
        params={"start": "9999-12-27T00:00:00", "end": "9999-12-28T00:00:00"},
    )
    assert hit.status_code == 200, hit.text
    assert [o["start_at"] for o in _rows(hit, "sync")] == ["9999-12-27T09:00:00"]
    # Two steps: the seed floors to the 20th, a firing time earlier in the day than
    # this window opens, and the 27th is the second one.
    assert step_counter["steps"] == 2


def test_long_event_end_does_not_overflow_the_calendar(ws_id, quiet_client, step_counter):
    """The other way out of the date range: an occurrence's own end, not its start.

    ``end_at`` is not validated against ``start_at``, so a daily event created to
    run up to 9999-12-31 carries a ``duration`` that pushes
    ``start_at + duration`` past ``datetime.max`` on its very second step — the
    same uncaught ``OverflowError`` as the weekly case, from a different line, and
    one neither bound reaches. Such an occurrence overlaps every window, so the
    row cap ends the walk; the first row keeps the end it had before the clamp and
    the rest are the clamped ones that used to raise.
    """
    _create(
        quiet_client,
        ws_id,
        "marathon",
        dt.datetime(2026, 1, 1, 9, 0),
        end_at=dt.datetime(9999, 12, 31, 9, 0),
    )
    resp = _list(
        quiet_client, ws_id, dt.datetime(9999, 12, 30), dt.datetime(9999, 12, 31), step_counter
    )

    assert resp.status_code == 200, resp.text
    occ = _rows(resp, "marathon")
    assert len(occ) == ROW_CAP, "the row cap binds, so the walk was not truncated"
    assert step_counter["steps"] == ROW_CAP
    assert occ[0]["end_at"] == "9999-12-31T09:00:00"
    assert occ[1]["end_at"] == "9999-12-31T23:59:59.999999"


def test_an_event_whose_end_precedes_its_start_still_answers(ws_id, quiet_client, step_counter):
    """The seed's threshold is the arithmetic a reversed event can push off the calendar.

    ``end_at`` is never validated against ``start_at``, so a negative duration shifts
    the earliest relevant occurrence start *forwards* — for a year-9999 window that
    means past ``datetime.max``, which is an ``OverflowError`` and a 500 unless the
    shift is clamped. Such an occurrence ends before it begins, so no window that
    opens after its own start can hold it, and the answer for the far range is empty
    either way: what is pinned is that it arrives as an empty 200 rather than a crash.
    """
    _create(
        quiet_client,
        ws_id,
        "reversed",
        dt.datetime(2026, 1, 1, 9, 0),
        "daily",
        end_at=dt.datetime(2020, 1, 1, 9, 0),
    )

    resp = _list(
        quiet_client, ws_id, dt.datetime(9999, 12, 30), dt.datetime(9999, 12, 31), step_counter
    )
    assert resp.status_code == 200, resp.text
    assert _rows(resp, "reversed") == []

    # Control that the empty body above is a window answer and not a dropped event:
    # a range opening before the occurrence's (earlier) end still gets the row. That
    # span is wider than the endpoint admits, so it is reached by a direct call.
    anchor = dt.datetime(2026, 1, 1, 9, 0)
    event = _mk_event("daily", start=anchor, end=dt.datetime(2020, 1, 1, 9, 0))
    rows = _expand_occurrences(
        event, dt.datetime(2020, 1, 1, 9, 0), dt.datetime(2026, 1, 1, 12, 0)
    )
    assert [(o.start_at, o.end_at) for o in rows] == [(anchor, dt.datetime(2020, 1, 1, 9, 0))]


def test_a_duration_longer_than_the_calendar_backs_the_seed_to_the_start_of_time(
    ws_id, quiet_client, step_counter
):
    """The clamp at the near end of the seed's threshold, reached from the client.

    ``_earliest_relevant_start`` shifts the window open backwards by the event's
    duration and clamps at ``datetime.min`` once the shift leaves the calendar. It
    is not exotic: the marathon event above spans 2,912,442 days, so the clamp holds
    for every window opening before 7974-12-31 — the first three quarters of the
    years the endpoint's own date parsing admits — and without it the shift raises
    ``OverflowError``, the same 500 its sibling pins in the other direction.
    Neither neighbour reaches it: the marathon test shifts the very same duration
    from 9999-12-30, which the shift fits inside, the reversed event has a negative
    duration and lands on the far clamp instead, and the differential's longest
    duration is four hours.

    A clamped threshold means "skip nothing", which is the right answer here: an
    occurrence that runs to the calendar limit overlaps every window, including one
    974 years past the anchor. So the walk starts at the anchor and fills to the row
    cap with 2026 dates, none of them inside the requested year-3000 window — the
    rows the clamp keeps, which is what the pinned shape is for.
    """
    anchor = dt.datetime(2026, 1, 1, 9, 0)
    far_end = dt.datetime(9999, 12, 31, 9, 0)
    event = _create(quiet_client, ws_id, "aeon", anchor, "daily", end_at=far_end)

    # The precondition is part of the assertion, not an assumption about the date:
    # this window really is inside the clamp's reach...
    window_start = dt.datetime(3000, 1, 1)
    assert far_end - anchor > window_start - dt.datetime.min
    # ...and the sibling's year-9999 window really is outside it, so the two tests
    # cover the two branches of one line rather than the same branch twice.
    assert far_end - anchor <= dt.datetime(9999, 12, 30) - dt.datetime.min

    resp = _list(
        quiet_client, ws_id, window_start, window_start + dt.timedelta(days=1), step_counter
    )

    assert resp.status_code == 200, resp.text
    occ = _rows(resp, "aeon")
    assert len(occ) == ROW_CAP, "the row cap binds, so the walk was not truncated"
    assert step_counter["steps"] == ROW_CAP
    assert occ[0]["occurrence_id"] == f"{event['id']}@2026-01-01"
    assert [o["start_at"] for o in occ[:2]] == ["2026-01-01T09:00:00", "2026-01-02T09:00:00"]
    assert occ[-1]["start_at"] == "2026-07-19T09:00:00"
    assert occ[0]["end_at"] == "9999-12-31T09:00:00"
    assert {o["end_at"] for o in occ[1:]} == {"9999-12-31T23:59:59.999999"}


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


@pytest.mark.parametrize(
    "anchor",
    [
        dt.datetime(2026, 1, 31, 9, 0),
        dt.datetime(2026, 4, 30, 9, 0),
        dt.datetime(2000, 2, 29, 9, 0),
        dt.datetime(2100, 2, 28, 9, 0),
        dt.datetime(2026, 9, 1, 9, 0),
    ],
)
def test_monthly_at_reproduces_the_iterated_clamp(anchor):
    """The one-step monthly form agrees with stepping, month for month.

    The seed computes where a monthly walk would be after ``months`` steps. If
    that date is not the one stepping reaches, the seeded walk answers a far window
    with dates the same event never produces up close — a Jan 31 anchor fires on
    the 28th once February has passed and does not drift back. The sweep below runs
    to 400 months, the depth at which ``_monthly_at`` stops folding the day, and one
    step past it, so the truncation is on the path.
    """
    stepped = anchor
    for months in range(401):
        if months:
            stepped = _next_occurrence(stepped, "monthly")
            assert stepped is not None
        assert _monthly_at(anchor, months) == stepped, f"{anchor} + {months} months"

    # One step past the sweep's ceiling, so the shortcut is on the path here.
    past = _next_occurrence(stepped, "monthly")
    assert _monthly_at(anchor, 401) == past


# ---------------------------------------------------------------------------
# Where the limits sit — in the work a request costs, and in the printed docs
# ---------------------------------------------------------------------------


def test_the_widest_admitted_window_costs_its_own_width_in_steps(step_counter):
    """The relation the step bound's headroom is judged against, walked for real.

    A daily event asked for the widest range the endpoint admits, once from an
    anchor five years before that range and once from an anchor at its start: both
    cost the window, not the distance to it, which is what makes the step ceiling a
    backstop instead of the thing that decides an answer. ``cap`` is raised past the
    ceiling so it cannot be what stops the walk here.
    """
    event = _mk_event("daily", start=dt.datetime(2026, 1, 1, 9, 0))
    wide = MAX_EXPANSION_RANGE.days * 2

    step_counter["steps"] = 0
    _expand_occurrences(
        event,
        dt.datetime(2031, 1, 1),
        dt.datetime(2031, 1, 1) + MAX_EXPANSION_RANGE,
        cap=wide,
    )
    far_from_anchor = step_counter["steps"]

    step_counter["steps"] = 0
    _expand_occurrences(
        event,
        dt.datetime(2026, 1, 1, 9, 0),
        dt.datetime(2026, 1, 1, 9, 0) + MAX_EXPANSION_RANGE,
        cap=wide,
    )
    at_the_anchor = step_counter["steps"]

    assert at_the_anchor == far_from_anchor == MAX_EXPANSION_RANGE.days + 1
    assert far_from_anchor < MAX_EXPANSION_STEPS, "the backstop is not what ended either"


def test_step_bound_leaves_headroom_and_stays_far_below_the_measured_burn():
    """Where the constants sit relative to real use and to the measured work.

    Five times the widest walk a legitimate request can now ask for
    (``MAX_EXPANSION_RANGE`` of daily occurrences, ~1,830 steps, pinned by the test
    above) at the bottom, a fraction of the 2.9M-step walk that was measured
    costing seconds at the top, and far away from the row cap so nobody can read one
    bound as the other.
    """
    widest_legitimate_daily_walk = MAX_EXPANSION_RANGE.days
    assert widest_legitimate_daily_walk * 5 <= MAX_EXPANSION_STEPS
    assert MAX_EXPANSION_STEPS <= MEASURED_UNBOUNDED_STEPS // 25
    assert ROW_CAP * 50 < MAX_EXPANSION_STEPS
    assert MAX_EXPANSION_RANGE >= dt.timedelta(days=365 * 5)


def test_the_limits_the_api_guide_prints_are_the_ones_shipped():
    """docs/API.md quotes a horizon, a row cap and a step ceiling for this endpoint.

    That row is what a client reads to decide how wide a range to ask for, and it is
    prose: nothing else in the suite reads those figures back against the code, so
    the three numbers it states are asserted against the constants and the default
    ``cap`` they describe.
    """
    row = next(
        line
        for line in DOC_PATH.read_text(encoding="utf-8").splitlines()
        if "`/workspaces/{id}/events`" in line
    )
    shipped_cap = inspect.signature(_expand_occurrences).parameters["cap"].default

    assert (MAX_EXPANSION_RANGE, shipped_cap, MAX_EXPANSION_STEPS) == (
        dt.timedelta(days=1830),
        ROW_CAP,
        20_000,
    )
    assert f"{MAX_EXPANSION_RANGE.days} days" in row
    assert f"{shipped_cap} occurrences" in row
    assert f"{MAX_EXPANSION_STEPS:,} stepped dates" in row
