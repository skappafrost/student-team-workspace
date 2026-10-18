"""SQLite/PostgreSQL behavioral parity suite (TA5-2).

CI runs the backend suite twice (``backend`` job on SQLite, ``backend-pg`` job
on Postgres), so the two jobs can only catch dialect drift if the *same* test
assertions actually run on both engines. Historically that was not the case for
whole code paths (see the accompanying fixes to test_recurrence_api.py /
test_models.py, whose engines used to be hard-coded to SQLite). This module
locks the remaining divergence classes down:

1. ``ilike`` search case-insensitivity -- ``x.ilike()`` compiles to native
   ``ILIKE`` on Postgres and to ``lower(x) LIKE lower(...)`` on SQLite. Both
   are case-insensitive, but a regression to plain ``like()`` on either side
   would silently change results. We assert exact row-set equality of the
   ``?q=`` / ``?search=`` endpoints for mixed-case terms.
2. LIKE wildcard escaping -- the escaped ``%``/``_`` semantics from the search
   filters must hold on both dialects (the ``escape='\\'`` clause).
3. Boolean filters -- ``col.is_(False)`` is the portable spelling. On Postgres
   ``col == 0`` raises "operator does not exist: boolean = integer" while it
   silently works on SQLite; this suite pins the portable behavior.
4. DateTime round-trip -- ``DateTime(timezone=True)`` returns tz-aware values
   on Postgres and naive ones on SQLite; endpoints must normalize to naive UTC
   before serialization so the emitted JSON is identical on both.
5. Recurring-event expansion -- the naive/aware normalization fix in
   routers/events.py; without it, every recurring list-with-range request
   returns 500 on Postgres (this suite reproduces it directly).
6. SQL-side range filters, ``ORDER BY ... NULLS LAST`` and ``LIMIT``/``OFFSET`` --
   ``GET /users/me/tasks`` now buckets ``?due=`` and slices the page inside the
   query instead of in Python, so the comparison runs against a ``timestamptz``
   column on Postgres and against the driver's fixed text form on SQLite. Every
   other suite touching that endpoint builds a hardcoded SQLite engine, which is
   why the cases live here.

Rules (task contract):

* Tests run on SQLite locally and on Postgres on the ``backend-pg`` CI job via
  the ``DATABASE_URL`` honored by ``conftest``. No dialect-specific setup here.
* No new endpoints and no response-shape changes: this file only asserts
  existing behavior on both engines.
"""

import datetime

import pytest

from conftest import as_user, make_user
from models import User

# ---------------------------------------------------------------------------
# Search case-insensitivity parity (ilike -> ILIKE / lower() LIKE)
# ---------------------------------------------------------------------------


def _make_channel(client, db_session, workspace_id, channel_name="general"):
    make_user(db_session, "owner")
    as_user(client, "owner")
    resp = client.post(
        f"/workspaces/{workspace_id}/channels",
        json={"name": channel_name, "type": "general"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_message_search_case_insensitive_parity(client, db_session):
    """`?q=` must return the same rows on SQLite and Postgres for a mixed-case
    term, regardless of the underlying LIKE implementation."""
    ws = _make_workspace(client, db_session)
    channel = _make_channel(client, db_session, ws["id"])

    def post(content):
        r = client.post(f"/channels/{channel['id']}/messages", json={"content": content})
        assert r.status_code == 201, r.text

    post("Release NOTES v2")
    post("release notes v2")
    post("unrelated chatter")

    # Stored content is mixed-case; the query is lowercase.
    rows = client.get(f"/channels/{channel['id']}/messages?q=release+notes").json()
    assert {m["content"] for m in rows} == {"Release NOTES v2", "release notes v2"}, rows

    # Uppercase query must match the same rows: ilike is case-insensitive on
    # BOTH dialects, so a case-sensitivity regression on either fails here.
    rows = client.get(f"/channels/{channel['id']}/messages?q=RELEASE+NOTES").json()
    assert {m["content"] for m in rows} == {"Release NOTES v2", "release notes v2"}, rows


def test_message_search_literal_wildcards_parity(client, db_session):
    """A term containing ``%`` and ``_`` must match literally, not as SQL
    wildcards, on both dialects (the escaped LIKE clause from TA5-2's base)."""
    ws = _make_workspace(client, db_session, slug="parity-wild")
    channel = _make_channel(client, db_session, ws["id"], channel_name="wildcards")

    def post(content):
        r = client.post(f"/channels/{channel['id']}/messages", json={"content": content})
        assert r.status_code == 201, r.text

    post("Kế hoạch đạt 100% vào tuần sau")
    post("Task 3_1 đã xong")
    post("unrelated chatter")

    # Literal "100%" must match only the message that literally contains it.
    rows = client.get(f"/channels/{channel['id']}/messages", params={"q": "100%"}).json()
    contents = [m["content"] for m in rows]
    assert contents == ["Kế hoạch đạt 100% vào tuần sau"], contents

    # Literal "3_1" must match only the underscore message, never "AxB".
    rows = client.get(f"/channels/{channel['id']}/messages", params={"q": "3_1"}).json()
    contents = [m["content"] for m in rows]
    assert contents == ["Task 3_1 đã xong"], contents

    # A lone wildcard must only match rows that literally contain it.
    rows = client.get(f"/channels/{channel['id']}/messages", params={"q": "%"}).json()
    contents = [m["content"] for m in rows]
    assert contents == ["Kế hoạch đạt 100% vào tuần sau"], contents

    rows = client.get(f"/channels/{channel['id']}/messages", params={"q": "_"}).json()
    contents = [m["content"] for m in rows]
    assert contents == ["Task 3_1 đã xong"], contents


# ---------------------------------------------------------------------------
# Page search parity (same ilike semantics on title + content)
# ---------------------------------------------------------------------------


def _make_page(client, workspace_id, title, slug, content):
    r = client.post(
        f"/workspaces/{workspace_id}/pages",
        json={"title": title, "slug": slug, "content": content},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_page_search_case_and_wildcards_parity(client, db_session):
    ws = _make_workspace(client, db_session, slug="parity-pages")
    _make_page(client, ws["id"], "Deployment Guide", "deployment-guide", "Deploy to PROD")
    _make_page(client, ws["id"], "Onboarding", "onboarding", "nothing special")

    # Mixed-case term, case-insensitive match on both dialects.
    rows = client.get(f"/workspaces/{ws['id']}/pages?search=deploy").json()
    assert {p["title"] for p in rows} == {"Deployment Guide"}, rows

    # Content match with a different case than stored.
    rows = client.get(f"/workspaces/{ws['id']}/pages?search=PROD").json()
    assert {p["title"] for p in rows} == {"Deployment Guide"}, rows

    # Empty term returns [] (never a wildcard dump of every row).
    rows = client.get(f"/workspaces/{ws['id']}/pages?search=").json()
    assert rows == [], rows


# ---------------------------------------------------------------------------
# Boolean filter parity
# ---------------------------------------------------------------------------


def test_notification_read_filter_parity(client, db_session):
    """``unread_only`` uses ``col.is_(False)`` -- the portable spelling. On
    Postgres ``col == 0`` raises "operator does not exist: boolean = integer",
    so this test hard-fails there if the filter ever regresses to that."""
    owner = make_user(db_session, "owner")
    as_user(client, "owner")
    _make_workspace(client, db_session, slug="parity-notif")

    from models import Notification

    def notify(title):
        db_session.add(Notification(user_id=owner.id, type="system", title=title, content="x"))
        db_session.commit()

    notify("unread one")
    notify("unread two")

    all_rows = client.get("/notifications").json()
    assert len(all_rows) == 2, all_rows

    unread = client.get("/notifications?unread_only=true").json()
    assert {n["title"] for n in unread} == {"unread one", "unread two"}, unread

    # Mark one read, then the filter must shrink identically on both dialects.
    first = all_rows[0]
    r = client.patch(f"/notifications/{first['id']}", json={"read": True})
    assert r.status_code == 200, r.text

    unread = client.get("/notifications?unread_only=true").json()
    assert {n["title"] for n in unread} == {all_rows[1]["title"]}, unread


# ---------------------------------------------------------------------------
# DateTime round-trip parity
# ---------------------------------------------------------------------------


def _naive_utc(value):
    if value.tzinfo is not None:
        return value.astimezone(datetime.UTC).replace(tzinfo=None)
    return value


def test_datetime_roundtrip_parity(client, db_session):
    """``DateTime(timezone=True)`` stores timestamptz on Postgres and naive
    TEXT on SQLite; both must serialize to the same JSON string."""
    ws = _make_workspace(client, db_session, slug="parity-events")
    as_user(client, "owner")
    r = client.post(
        f"/workspaces/{ws['id']}/events",
        json={
            "title": "Parity Event",
            "start_at": "2026-08-28T09:00:00",
            "end_at": "2026-08-28T10:00:00",
            "all_day": False,
            "event_type": "meeting",
        },
    )
    assert r.status_code == 201, r.text
    event = r.json()

    # Serialized value must be naive UTC on both dialects: no "+00:00" suffix
    # and no offset shift between engines.
    assert event["start_at"] == "2026-08-28T09:00:00", event["start_at"]
    assert event["end_at"] == "2026-08-28T10:00:00", event["end_at"]

    # ORM round-trip: whatever tzinfo the engine hands back, normalizing to
    # naive UTC must reproduce the same instant.
    from models import Event

    row = db_session.query(Event).filter(Event.id == event["id"]).one()
    assert _naive_utc(row.start_at) == datetime.datetime(2026, 8, 28, 9, 0, 0)
    assert _naive_utc(row.end_at) == datetime.datetime(2026, 8, 28, 10, 0, 0)


def test_server_default_timestamp_parity(db_session):
    """``server_default=func.now()`` is ``CURRENT_TIMESTAMP`` on SQLite and
    ``now()`` on Postgres. Both must populate the column (never NULL) and the
    value must be close to wall-clock UTC."""
    user = User(id="parity_user", email="parity@example.com", display_name="Parity")
    db_session.add(user)
    db_session.commit()
    db_session.expire_all()

    row = db_session.query(User).filter(User.id == "parity_user").one()
    assert row.created_at is not None, "server_default func.now() produced NULL"

    now = _naive_utc(datetime.datetime.now(datetime.UTC))
    delta = abs((now - _naive_utc(row.created_at)).total_seconds())
    assert delta < 300, f"server_default timestamp drifted {delta}s from wall clock"


# ---------------------------------------------------------------------------
# Recurring-event expansion parity (the naive/aware divergence fix)
# ---------------------------------------------------------------------------


def test_recurring_event_list_range_parity(client, db_session):
    """Listing recurring events within a date range must expand the same
    occurrences on both dialects.

    Before TA5-2 this 500'd on Postgres: ``_expand_occurrences`` compared
    ``event.start_at`` (tz-aware under timestamptz) against range bounds parsed
    naive from the query string -> ``TypeError: can't compare offset-naive and
    offset-aware datetimes``. On SQLite the same code worked, so the suite was
    green locally while backend-pg would have 500'd.
    """
    ws = _make_workspace(client, db_session, slug="parity-recurring")
    as_user(client, "owner")
    r = client.post(
        f"/workspaces/{ws['id']}/events",
        json={
            "title": "standup",
            "start_at": "2026-09-03T09:00:00",
            "end_at": "2026-09-03T09:30:00",
            "recurrence": "daily",
            "event_type": "meeting",
            "all_day": False,
        },
    )
    assert r.status_code == 201, r.text

    resp = client.get(
        f"/workspaces/{ws['id']}/events",
        params={"start": "2026-09-03T00:00:00", "end": "2026-09-06T23:59:59"},
    )
    assert resp.status_code == 200, resp.text
    mine = [e for e in resp.json() if e["title"] == "standup"]
    # 2026-09-03 .. 2026-09-06 inclusive = 4 occurrences.
    assert len(mine) == 4, [e["occurrence_id"] for e in mine]
    assert all(e["occurrence_id"] is not None for e in mine), mine

    # Each occurrence carries the same duration as the base event.
    for e in mine:
        assert e["start_at"].endswith("09:00:00"), e
        assert e["end_at"].endswith("09:30:00"), e

    # Without a range, the base event is returned as-is.
    resp = client.get(f"/workspaces/{ws['id']}/events")
    assert resp.status_code == 200, resp.text
    mine = [e for e in resp.json() if e["title"] == "standup"]
    assert len(mine) == 1
    assert mine[0]["occurrence_id"] is None


# ---------------------------------------------------------------------------
# Unique-constraint NULL semantics (verified on both engines, not assumed)
# ---------------------------------------------------------------------------


def test_unique_constraint_nulls_parity(db_session):
    """Both SQLite and Postgres treat NULLs as distinct in a plain UNIQUE
    constraint, so nullable columns can hold many NULLs; the composite unique
    constraints still reject duplicate non-null pairs on both."""
    from sqlalchemy.exc import IntegrityError

    from models import Document, User, Workspace, WorkspaceMember

    user = User(id="parity_null_u", email="parity_null@example.com", display_name="N")
    workspace = Workspace(name="W", slug="w-parity-null")
    db_session.add_all([user, workspace])
    db_session.commit()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db_session.commit()

    # project_id is nullable -> two rows with NULL project_id are both fine.
    db_session.add_all(
        [
            Document(workspace_id=workspace.id, project_id=None, author_id=user.id, title="d1"),
            Document(workspace_id=workspace.id, project_id=None, author_id=user.id, title="d2"),
        ]
    )
    db_session.commit()

    # A duplicate NON-null (workspace, user) membership pair is still rejected.
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member"))
    with pytest.raises(IntegrityError):
        try:
            db_session.flush()
        finally:
            db_session.rollback()


# ---------------------------------------------------------------------------
# my-tasks due buckets / ordering / paging (the SQL pushed into routers/tasks.py)
# ---------------------------------------------------------------------------


def _my_tasks_board(client, db_session, slug):
    """Owner-run workspace + board, i.e. rows ``GET /users/me/tasks`` can see."""
    ws = _make_workspace(client, db_session, name=f"mt-{slug}", slug=slug)
    resp = client.post(f"/workspaces/{ws['id']}/projects", json={"name": f"Board {slug}"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_my_tasks(client, db_session, slug):
    """Seed seven of the caller's own tasks and return the ``(title, due_at)`` used.

    Five dated rows, one per non-NULL bucket, with **distinct** due dates, plus two
    undated ones. Distinct dues make the ``ORDER BY due_at`` prefix a total order, so
    every page is a fixed list of titles on either engine; the two NULL rows are only
    ever asserted as a group, because which of them lands first is the database's
    business and was never specified.
    """
    board = _my_tasks_board(client, db_session, slug)
    now = datetime.datetime.now(datetime.UTC)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    # The midpoint of the window still left today: strictly later than ``now`` and
    # never past ``today_end``, whatever hour the suite starts at. Seeding "an hour
    # from now" instead would put the row in tomorrow's bucket for any run after
    # 23:00 UTC, and the ``today`` leg would then assert nothing.
    rows = [
        ("overdue-old", now - datetime.timedelta(days=3)),
        ("overdue-recent", now - datetime.timedelta(hours=5)),
        ("due-today", now + (today_end - now) / 2),
        ("due-week", now + datetime.timedelta(days=3)),
        ("due-later", now + datetime.timedelta(days=30)),
        ("undated-a", None),
        ("undated-b", None),
    ]
    for title, due in rows:
        payload = {"title": title, "assignee_id": "owner"}
        if due is not None:
            payload["due_at"] = due.isoformat()
        resp = client.post(f"/projects/{board}/tasks", json=payload)
        assert resp.status_code == 201, resp.text
    return rows


DATED_IN_ORDER = ["overdue-old", "overdue-recent", "due-today", "due-week", "due-later"]


def test_my_tasks_due_bucket_parity(client, db_session):
    """``?due=`` must put the same rows in the same bucket on both engines.

    The buckets are SQL range comparisons against aware-UTC constants since the
    over-fetch fix, so on Postgres they run against a ``timestamptz`` column -- where
    a session-timezone shift or a naive/aware bind slip moves the boundary -- and on
    SQLite against the driver's ``%Y-%m-%d %H:%M:%S.%f`` text form, where the
    comparison is only chronological because that format is fixed-width. Neither
    failure shows up in the endpoint's own suites: all three of them build a
    hardcoded SQLite engine, so on the Postgres job nothing sent ``due=`` through the
    new SQL at all.
    """
    rows = _seed_my_tasks(client, db_session, "parity-mytasks-buckets")

    def bucket(due):
        resp = client.get("/users/me/tasks", params={"due": due})
        assert resp.status_code == 200, resp.text
        return [t["title"] for t in resp.json()]

    # Both legs must agree that exactly the two past-dated rows are overdue, in
    # ascending-due order, and that the row seeded inside today's window is the only
    # one today. A boundary that moved on one engine answers with a different list.
    assert bucket("overdue") == ["overdue-old", "overdue-recent"]
    assert bucket("today") == ["due-today"]
    assert bucket("week") == ["due-week"]
    assert bucket("later") == ["due-later"]
    # The two undated rows tie on NULL, so only their membership is asserted.
    assert sorted(bucket("none")) == ["undated-a", "undated-b"]

    # The five buckets partition the seven rows: a range that overlapped, or a NULL
    # that started satisfying a comparison, would show up as a repeat or a gap.
    distributed = [
        title for due in ("overdue", "today", "week", "later", "none") for title in bucket(due)
    ]
    assert len(distributed) == 7, distributed
    assert sorted(distributed) == sorted(title for title, _ in rows), (
        "the buckets no longer cover exactly the rows the caller owns"
    )


def test_my_tasks_page_and_undated_tail_parity(client, db_session):
    """``ORDER BY due_at ASC NULLS LAST`` + ``LIMIT``/``OFFSET`` page the same rows.

    SQLite grew ``NULLS LAST`` in 3.30 and Postgres has always had it, but the clause
    is only half of the contract: the other half is that undated rows land after every
    dated one and that slicing in the database neither drops nor repeats a row. The
    page arithmetic is asserted on both engines from one seed, so the leg that stops
    honouring either clause fails here instead of shipping.
    """
    rows = _seed_my_tasks(client, db_session, "parity-mytasks-pages")

    def page(**params):
        resp = client.get("/users/me/tasks", params=params)
        assert resp.status_code == 200, resp.text
        return [t["title"] for t in resp.json()]

    whole = page()
    assert whole[:5] == DATED_IN_ORDER, whole
    assert sorted(whole[5:]) == ["undated-a", "undated-b"], whole

    # Pages over the dated prefix: fully determined by the sort key.
    assert page(limit=2, offset=0) == DATED_IN_ORDER[0:2]
    assert page(limit=2, offset=2) == DATED_IN_ORDER[2:4]
    assert page(limit=1, offset=4) == ["due-later"]
    # Every page boundary past the dated rows cuts through the NULL group, whose
    # internal order no engine promises -- so assert coverage, not order: OFFSET must
    # neither skip a row nor serve it twice.
    sliced = [page(limit=2, offset=offset) for offset in (0, 2, 4, 6)]
    assert [len(p) for p in sliced] == [2, 2, 2, 1], sliced
    assert sorted(title for p in sliced for title in p) == sorted(whole), sliced

    # An OFFSET past the end is an empty page, not a wrap-around to the first rows.
    assert page(limit=2, offset=20) == []

    # The instants the buckets compared are the instants that were stored: on
    # Postgres this is the timestamptz/session-timezone round trip, on SQLite it is
    # the fixed-width text form, and both must reproduce the seeded instant.
    returned = client.get("/users/me/tasks").json()
    by_title = {t["title"]: t["due_at"] for t in returned}
    for title, due in rows:
        if due is None:
            assert by_title[title] is None, title
            continue
        assert datetime.datetime.fromisoformat(by_title[title]) == due, (
            title,
            by_title[title],
            due,
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_workspace(client, db_session, name="parity-ws", slug="parity-ws"):
    make_user(db_session, "owner")
    as_user(client, "owner")
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()
