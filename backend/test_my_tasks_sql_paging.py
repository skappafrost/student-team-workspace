"""GET /users/me/tasks must order and page in SQL, not in Python.

INSTRUMENT (named so the numbers below are checkable): a DBAPI cursor proxy.
SQLAlchemy 2.0.52 has no ``handle_row`` event, so fetched rows are counted where
the driver actually hands them over — the test engine is created with
``connect_args={"factory": CountingConnection}``, a ``sqlite3.Connection``
subclass whose cursor adds ``len()`` of every ``fetchall``/``fetchmany``/
``fetchone`` to the statement that produced it. ``before_cursor_execute`` counts
statements as an independent cross-check, and the measurement tests assert the two
agree (``len(recorder.statements) == recorder.sa_statements``) so a proxy that
silently stopped counting cannot report a fetch count of zero as a win.

Measured with that instrument on the fetch-everything implementation, 300 tasks
assigned to one identity:

    ?limit=10            -> 1 statement, 300 rows fetched, 10 returned  (30.0x)
    ?limit=10&due=today  -> 1 statement, 300 rows fetched,  8 returned  (37.5x)
    ?limit=10&offset=290 -> 1 statement, 300 rows fetched, 10 returned  (30.0x)
    limit=10 over 30     -> 1 statement,  30 rows fetched, 10 returned  ( 3.0x)

and the recorded SQL carried neither ``ORDER BY`` nor ``LIMIT``. Fetched rows
tracked the table, not the page. After pushing the order, the due bucket and the
page slice into the query, the same instrument reports one statement per request
whose fetched-row count equals the page the endpoint returned — the measurement
tests assert ``fetched == len(body)`` for a non-empty page, never an upper bound —
and the 30-row and 300-row datasets fetch the same number of rows.

The controls pin the results first: the endpoint has to keep returning exactly
what "fetch all, sort in Python, slice in Python" returned — same rows, same
order — including over a dataset whose equal-``due_at`` tie group straddles the
page edge, where which rows land on the page is the whole question.
"""

import datetime
import sqlite3
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import models
from app import app, create_access_token
from database import get_db
from models import Project, Task, User, Workspace, WorkspaceMember

DB_URL = "sqlite:///./test_stw_mytasks_paging.db"
MEASURED_PATH = "/users/me/tasks"


class Recorder:
    """Per-statement row counts collected at the DBAPI cursor layer."""

    def __init__(self):
        self._lock = threading.Lock()
        self.statements: list = []
        self.current = None
        self.sa_statements = 0

    def begin(self, sql):
        with self._lock:
            entry = {"sql": " ".join(sql.split()), "rows": 0}
            self.statements.append(entry)
            self.current = entry

    def add_rows(self, n):
        with self._lock:
            if self.current is not None:
                self.current["rows"] += n

    def reset(self):
        with self._lock:
            self.statements = []
            self.current = None
            self.sa_statements = 0

    def task_select_rows(self):
        """Rows fetched by the statement(s) that read the ``tasks`` table."""
        with self._lock:
            return [
                (s["sql"], s["rows"])
                for s in self.statements
                if s["sql"].lstrip().upper().startswith("SELECT") and "from tasks" in s["sql"].lower()
            ]


recorder = Recorder()


class _CountingCursor(sqlite3.Cursor):
    def execute(self, sql, *args):
        recorder.begin(sql)
        return super().execute(sql, *args)

    def executemany(self, sql, *args):
        recorder.begin(sql)
        return super().executemany(sql, *args)

    def fetchall(self):
        rows = super().fetchall()
        recorder.add_rows(len(rows))
        return rows

    def fetchmany(self, size=None, **kwargs):
        # ``fetchmany()`` with no argument is what a streamed result calls, and it
        # means "the next arraysize rows". Forwarding the None as -1 does not: this
        # interpreter's sqlite3 raises ``ValueError: Cannot convert negative int``,
        # so the proxy would break the very path it is there to measure.
        if size is None:
            rows = super().fetchmany(**kwargs)
        else:
            rows = super().fetchmany(size, **kwargs)
        recorder.add_rows(len(rows))
        return rows

    def fetchone(self):
        row = super().fetchone()
        recorder.add_rows(1 if row is not None else 0)
        return row


class _CountingConnection(sqlite3.Connection):
    def cursor(self, factory=None, **kwargs):
        return super().cursor(factory or _CountingCursor, **kwargs)


engine = create_engine(
    DB_URL,
    echo=False,
    future=True,
    connect_args={"factory": _CountingConnection, "check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    models.Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        for table in reversed(models.Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
        db.close()
        models.Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def _get_db_override():
        return db_session

    app.dependency_overrides[get_db] = _get_db_override
    _client = TestClient(app)
    _client._db = db_session
    yield _client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _recording():
    """Install the statement counter the measurement tests cross-check the proxy against."""

    def _before(conn, cur, statement, params, context, executemany):
        recorder.sa_statements += 1

    event.listen(engine, "before_cursor_execute", _before)
    recorder.reset()
    try:
        yield recorder
    finally:
        event.remove(engine, "before_cursor_execute", _before)
        recorder.reset()


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _workspace(db, user_id: str, slug: str, member: bool = True) -> str:
    ws = Workspace(name=f"WS-{slug}", slug=slug)
    db.add(ws)
    db.flush()
    if member:
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user_id, role="owner"))
    proj = Project(workspace_id=ws.id, owner_id=user_id, name=f"P-{slug}")
    db.add(proj)
    db.flush()
    return proj.id


def seed_page_matrix(db, user_id: str) -> dict:
    """Rows that exercise every ordering edge the Python sort used to resolve.

    Distinct dues, a four-way ``due_at`` tie, undated rows, a second workspace,
    a task in a workspace the caller is not a member of, and an unassigned task.
    """
    now = datetime.datetime.now(datetime.UTC)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    # Clamp so a run near midnight cannot roll the tie group into tomorrow and
    # move it between the "today" and "week" buckets mid-test.
    tie_due = min(now + datetime.timedelta(hours=1), today_end - datetime.timedelta(minutes=1))

    def add(project_id, title, due_at=None, status="todo", assignee=user_id):
        task = Task(
            project_id=project_id,
            assignee_id=assignee,
            title=title,
            status=status,
            position=0.0,
            due_at=due_at,
        )
        db.add(task)
        db.flush()
        return task.id

    foreign = new_uid("p-foreign")
    if not db.query(User).filter(User.id == foreign).first():
        db.add(User(id=foreign, email=f"{foreign}@example.com", display_name=foreign))
        db.flush()

    proj_a = _workspace(db, user_id, f"paging-a-{uuid.uuid4().hex[:6]}")
    proj_b = _workspace(db, user_id, f"paging-b-{uuid.uuid4().hex[:6]}")
    proj_c = _workspace(db, foreign, f"paging-c-{uuid.uuid4().hex[:6]}")

    ids = {
        "far_overdue": add(proj_a, "far-overdue", now - datetime.timedelta(hours=240)),
        "done_overdue": add(proj_a, "done-overdue", now - datetime.timedelta(hours=120), status="done"),
        "mid_overdue": add(proj_a, "mid-overdue", now - datetime.timedelta(hours=72)),
        "near_overdue": add(proj_a, "near-overdue", now - datetime.timedelta(hours=24)),
        "other_ws_overdue": add(proj_b, "other-ws-overdue", now - datetime.timedelta(hours=12)),
        "tie": [add(proj_a, f"tie-{i}", tie_due) for i in range(4)],
        "week": add(proj_a, "week", now + datetime.timedelta(hours=72)),
        "other_ws_later": add(proj_b, "other-ws-later", now + datetime.timedelta(hours=120)),
        "later": add(proj_a, "later", now + datetime.timedelta(hours=720)),
        "none": [add(proj_a, f"none-{i}", None) for i in range(2)],
        # Invisible to the endpoint: assigned to the caller but outside every
        # workspace the caller is a member of, and an unassigned neighbour.
        "excluded_foreign": add(proj_c, "foreign-ws", now - datetime.timedelta(hours=5)),
        "excluded_unassigned": add(proj_a, "unassigned", now - datetime.timedelta(hours=6), assignee=None),
    }
    db.commit()
    return ids


def seed_bulk(db, user_id: str, n: int, slug: str) -> None:
    """``n`` assigned tasks, most of them due, for the row-count measurements."""
    proj = _workspace(db, user_id, slug)
    base = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    for i in range(n):
        db.add(
            Task(
                project_id=proj,
                assignee_id=user_id,
                title=f"task-{i}",
                status="todo",
                position=float(i),
                due_at=None if i % 10 == 9 else base + datetime.timedelta(hours=i),
            )
        )
    db.commit()


def seed_row_in_todays_bucket(db, user_id: str) -> None:
    """One task due in the middle of whatever part of today is left.

    ``seed_bulk`` starts its dues at the seed instant and steps forward an hour, so
    for a run after ~22:00 UTC the ``today`` bucket is empty — and a leg that returns
    nothing cannot tell "fetched one page" from "fetched the table and threw it away".
    The midpoint of the remaining window is after ``now`` and at or before
    ``today_end`` at any start hour, which keeps that leg measuring a non-empty bucket.
    """
    proj = _workspace(db, user_id, f"paging-today-{uuid.uuid4().hex[:6]}")
    now = datetime.datetime.now(datetime.UTC)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    due = (now + (today_end - now) / 2).replace(tzinfo=None)
    db.add(
        Task(
            project_id=proj,
            assignee_id=user_id,
            title="due-in-todays-window",
            status="todo",
            position=0.0,
            due_at=due,
        )
    )
    db.commit()


def new_uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def as_user(client: TestClient, uid: str) -> None:
    client.headers.update({"Authorization": f"Bearer {create_access_token(uid)}"})


# ---------------------------------------------------------------------------
# CONTROL — the results the Python implementation produced, pinned
# ---------------------------------------------------------------------------


def python_reference_page(db, uid, due=None, status=None, limit=None, offset=0):
    """The endpoint's previous algorithm, re-run in the test as the oracle.

    Fetch every matching row, filter the due bucket in Python, stable-sort by
    ``(due_at is None, due_at)``, then slice — i.e. exactly what
    ``list_my_tasks`` did before the page moved into SQL.
    """
    rows = (
        db.query(models.Task, models.Project, models.Workspace)
        .join(models.Project, models.Task.project_id == models.Project.id)
        .join(models.Workspace, models.Project.workspace_id == models.Workspace.id)
        .join(
            models.WorkspaceMember,
            (models.WorkspaceMember.workspace_id == models.Workspace.id)
            & (models.WorkspaceMember.user_id == uid),
        )
        .filter(models.Task.assignee_id == uid)
    )
    if status:
        rows = rows.filter(models.Task.status == status)

    now = datetime.datetime.now(datetime.UTC)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    week_end = today_end + datetime.timedelta(days=7)
    max_dt = datetime.datetime.max.replace(tzinfo=datetime.UTC)

    pairs = []
    for task in rows.all():
        t = task[0]
        due_at = t.due_at
        if due_at is not None and due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=datetime.UTC)
        if due == "overdue" and not (due_at and due_at < now):
            continue
        if due == "today" and not (due_at and now <= due_at <= today_end):
            continue
        if due == "week" and not (due_at and today_end < due_at <= week_end):
            continue
        if due == "later" and not (due_at and due_at > week_end):
            continue
        if due == "none" and due_at is not None:
            continue
        pairs.append((t.id, due_at))

    pairs.sort(key=lambda p: (p[1] is None, p[1] or max_dt))
    page = pairs[offset:] if offset else pairs
    if limit is not None:
        page = page[:limit]
    return [pid for pid, _ in page]


PAGE_CASES = [
    {},
    {"limit": 5},
    {"limit": 6},
    {"limit": 7},
    {"limit": 8, "offset": 3},
    {"offset": 4},
    {"limit": 3, "offset": 5},
    {"limit": 2, "offset": 12},
    {"limit": 1000},
    {"status": "done"},
    {"due": "overdue"},
    {"due": "today"},
    {"due": "week"},
    {"due": "later"},
    {"due": "none"},
    {"due": "nonsense"},
    {"due": "today", "limit": 2, "offset": 1},
    {"due": "overdue", "limit": 3},
    {"status": "todo", "due": "none", "limit": 1},
]


def test_control_page_equals_the_python_reference(client, db_session):
    """Every param combination must return the same ids in the same order."""
    uid = new_uid("p-control")
    if not db_session.query(User).filter(User.id == uid).first():
        db_session.add(User(id=uid, email=f"{uid}@example.com", display_name=uid))
        db_session.commit()
    seed_page_matrix(db_session, uid)
    as_user(client, uid)

    for params in PAGE_CASES:
        expected = python_reference_page(
            db_session,
            uid,
            due=params.get("due"),
            status=params.get("status"),
            limit=params.get("limit"),
            offset=params.get("offset", 0),
        )
        resp = client.get(MEASURED_PATH, params=params)
        assert resp.status_code == 200, (params, resp.text)
        got = [t["id"] for t in resp.json()]
        assert got == expected, f"page differs for {params}: {got} != {expected}"


def test_control_response_body_fields_and_wire_format(client, db_session):
    """The response shape is frozen: same keys, same naive-UTC ``created_at``,
    same ``Z``-suffixed ``due_at``, same enrichment fields."""
    uid = new_uid("p-shape")
    db_session.add(User(id=uid, email=f"{uid}@example.com", display_name=uid))
    db_session.commit()
    ids = seed_page_matrix(db_session, uid)
    as_user(client, uid)

    body = client.get(MEASURED_PATH, params={"limit": 3}).json()
    assert [t["id"] for t in body] == [
        ids["far_overdue"],
        ids["done_overdue"],
        ids["mid_overdue"],
    ]
    first = body[0]
    assert sorted(first) == [
        "assignee_id",
        "created_at",
        "description",
        "due_at",
        "id",
        "position",
        "priority",
        "project_id",
        "project_name",
        "status",
        "title",
        "updated_at",
        "workspace_name",
    ]
    assert first["due_at"].endswith("Z"), first["due_at"]
    assert not first["created_at"].endswith("Z"), first["created_at"]
    assert first["project_name"].startswith("P-paging-a-")
    assert first["workspace_name"].startswith("WS-paging-a-")


def test_control_tie_group_straddling_the_page_edge(client, db_session):
    """The case an unordered SQL sort could get wrong: four identical ``due_at``
    values, and the page cuts through them."""
    uid = new_uid("p-tie")
    db_session.add(User(id=uid, email=f"{uid}@example.com", display_name=uid))
    db_session.commit()
    seed_page_matrix(db_session, uid)
    as_user(client, uid)

    resp = client.get(MEASURED_PATH, params={"limit": 7})
    titles = [t["title"] for t in resp.json()]
    assert titles[:5] == [
        "far-overdue",
        "done-overdue",
        "mid-overdue",
        "near-overdue",
        "other-ws-overdue",
    ]
    # Two of the four tied rows make the page, in the order they were written —
    # the same two the fetch-all + stable Python sort put there.
    assert titles[5:] == ["tie-0", "tie-1"], titles
    full = [t["title"] for t in client.get(MEASURED_PATH).json()]
    assert full[5:9] == ["tie-0", "tie-1", "tie-2", "tie-3"], full


# ---------------------------------------------------------------------------
# MEASUREMENT — one page fetched, not one table
# ---------------------------------------------------------------------------


def _new_user(db, uid):
    if not db.query(User).filter(User.id == uid).first():
        db.add(User(id=uid, email=f"{uid}@example.com", display_name=uid))
        db.commit()


def test_measured_page_fetches_the_page(client, db_session):
    uid = new_uid("p-rows")
    _new_user(db_session, uid)
    seed_bulk(db_session, uid, 300, f"paging-300-{uuid.uuid4().hex[:6]}")
    as_user(client, uid)
    recorder.reset()
    resp = client.get(MEASURED_PATH, params={"limit": 10})
    assert resp.status_code == 200
    # The cross-check the module docstring promises, and the reason every fetched-row
    # number below means anything: the cursor proxy records one entry per execute on
    # this engine, ``before_cursor_execute`` counts the same statements from the other
    # side, and if the two ever disagree the proxy has stopped seeing the driver --
    # which would otherwise show up as a suspiciously perfect fetch count of zero.
    assert len(recorder.statements) == recorder.sa_statements, (
        f"cursor proxy recorded {len(recorder.statements)} statements, "
        f"before_cursor_execute recorded {recorder.sa_statements}"
    )
    task_selects = recorder.task_select_rows()
    fetched = sum(r for _, r in task_selects)
    print(
        f"MEASURE after(GET {MEASURED_PATH}?limit=10, 300 assigned tasks): "
        f"statements={recorder.sa_statements} rows_fetched={fetched} "
        f"returned={len(resp.json())} sql={task_selects[0][0][-90:] if task_selects else None}"
    )
    assert len(resp.json()) == 10
    assert fetched == 10, f"expected one page of rows, fetched {fetched}"
    assert recorder.sa_statements == 1


def test_measured_rows_do_not_grow_with_the_table(client, db_session):
    small = new_uid("p-small")
    big = new_uid("p-big")
    _new_user(db_session, small)
    _new_user(db_session, big)
    seed_bulk(db_session, small, 30, f"paging-30-{uuid.uuid4().hex[:6]}")
    seed_bulk(db_session, big, 300, f"paging-300-{uuid.uuid4().hex[:6]}")

    fetched = {}
    for label, uid in (("30", small), ("300", big)):
        as_user(client, uid)
        recorder.reset()
        resp = client.get(MEASURED_PATH, params={"limit": 10})
        fetched[label] = sum(r for _, r in recorder.task_select_rows())
        print(
            f"MEASURE after(dataset={label} tasks, limit=10): "
            f"rows_fetched={fetched[label]} returned={len(resp.json())}"
        )
        assert len(resp.json()) == 10
    assert fetched["30"] == fetched["300"] == 10, fetched


def test_measured_due_bucket_and_deep_offset_stay_one_page(client, db_session):
    """The bucket leg and the deep-offset leg each fetch the page and nothing more.

    ``fetched == len(body)`` rather than ``fetched <= 10``: an inequality is also true
    of a query that fetched 10 rows and returned 8 of them, and it is vacuously true of
    one that fetched nothing, which is what a run near 23:00 UTC used to get out of the
    ``due=today`` leg while the write-up printed "300 -> 8". Both legs now assert a
    non-empty page as well.
    """
    uid = new_uid("p-due")
    _new_user(db_session, uid)
    seed_bulk(db_session, uid, 300, f"paging-due-{uuid.uuid4().hex[:6]}")
    seed_row_in_todays_bucket(db_session, uid)
    as_user(client, uid)

    for params, expected_rows in (({"limit": 10, "due": "today"}, None), ({"limit": 10, "offset": 290}, 10)):
        recorder.reset()
        resp = client.get(MEASURED_PATH, params=params)
        body = resp.json()
        fetched = sum(r for _, r in recorder.task_select_rows())
        print(
            f"MEASURE after(GET {MEASURED_PATH}?{params}): statements={recorder.sa_statements} "
            f"rows_fetched={fetched} returned={len(body)}"
        )
        assert resp.status_code == 200
        assert len(body) > 0, f"{params} answered with an empty page, so the fetch count proves nothing"
        assert fetched == len(body), f"{params} fetched {fetched} rows for a {len(body)}-row page"
        if expected_rows is not None:
            assert len(body) == expected_rows


def test_measured_sql_carries_the_order_and_the_slice(client, db_session):
    uid = new_uid("p-sql")
    _new_user(db_session, uid)
    seed_bulk(db_session, uid, 300, f"paging-sql-{uuid.uuid4().hex[:6]}")
    as_user(client, uid)
    recorder.reset()
    client.get(MEASURED_PATH, params={"limit": 10, "due": "overdue"})
    sql = [s for s, _ in recorder.task_select_rows()]
    assert sql, "no tasks SELECT recorded"
    print(f"MEASURE after(emitted SQL): {sql[0][-160:]}")
    upper = sql[0].upper()
    assert "ORDER BY" in upper, sql[0]
    assert "LIMIT" in upper, sql[0]
    assert "NULLS LAST" in upper, sql[0]


def test_measured_default_page_size_still_returns_everything_small(client, db_session):
    """No ``limit`` = the 1000 cap, so a 14-row table still comes back whole."""
    uid = new_uid("p-all")
    db_session.add(User(id=uid, email=f"{uid}@example.com", display_name=uid))
    db_session.commit()
    seed_page_matrix(db_session, uid)
    as_user(client, uid)
    recorder.reset()
    resp = client.get(MEASURED_PATH)
    body = resp.json()
    print(
        f"MEASURE after(no limit param): statements={recorder.sa_statements} "
        f"rows_fetched={sum(r for _, r in recorder.task_select_rows())} returned={len(body)}"
    )
    assert resp.status_code == 200
    assert len(body) == 14, [t["title"] for t in body]
    assert [t["title"] for t in body][:5] == [
        "far-overdue",
        "done-overdue",
        "mid-overdue",
        "near-overdue",
        "other-ws-overdue",
    ]
    assert [t["title"] for t in body][-2:] == ["none-0", "none-1"]


def test_reference_select_ordering_matches_the_database(client, db_session):
    """Independent check of the order the endpoint now claims, straight from SQL."""
    uid = new_uid("p-order")
    db_session.add(User(id=uid, email=f"{uid}@example.com", display_name=uid))
    db_session.commit()
    seed_page_matrix(db_session, uid)
    as_user(client, uid)
    direct = [
        r[0]
        for r in db_session.execute(
            select(models.Task.id)
            .join(models.Project, models.Task.project_id == models.Project.id)
            .join(models.Workspace, models.Project.workspace_id == models.Workspace.id)
            .join(
                models.WorkspaceMember,
                (models.WorkspaceMember.workspace_id == models.Workspace.id)
                & (models.WorkspaceMember.user_id == uid),
            )
            .filter(models.Task.assignee_id == uid)
            .order_by(models.Task.due_at.asc().nulls_last())
        ).all()
    ]
    resp = client.get(MEASURED_PATH)
    assert [t["id"] for t in resp.json()] == direct
    assert "foreign-ws" not in [t["title"] for t in resp.json()]
