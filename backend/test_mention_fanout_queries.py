"""C3: the @mention fan-out must read the workspace's users in one SELECT.

``_resolve_mentions`` needs every member's display name, so it loaded the
workspace's membership rows and then touched ``membership.user`` on each one —
one lazy SELECT per member, inside ``POST /channels/{id}/messages``. The
instrument is the same ``before_cursor_execute`` listener
``test_nplus1_regression.py`` uses, recording the statement text so the reads
that hit ``users`` can be counted apart from the rest of the request.

Measured with that instrument, one mentioning message, 5 vs 25 workspace
members, on the per-member implementation:

    5 members  -> users SELECTs = 7,  request statements = 17
    25 members -> users SELECTs = 27, request statements = 37

— one read of ``users`` per member on top of a flat 2/9, growing the whole
request by exactly one statement per member. Eager-loading the same
relationship batches the roster into one ``users ... WHERE id IN (...)`` read:
both headcounts come back at 2 reads / 12 statements, and the roster read doubles
as the author lookup the fan-out already needed (the author is a member), so the
mentioning message costs one statement more than the same message without an
``@``.

The controls pin the *resolution*, not the count: which mentions resolve, to
whom, with which notification type, over a dataset built out of the awkward
cases (a name that is a prefix of another, two members whose names collide
modulo case, a member whose name is blank, a non-member whose name matches). A
batched load that changed who got notified would be the worse bug.
"""

import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from app import app, create_access_token
from database import get_db
from models import Channel, ChannelMember, User, Workspace, WorkspaceMember

DB_URL = "sqlite:///./test_stw_mention_fanout.db"
OWNER = "c3-owner"

TRICKY = [
    "Alice",          # the shortest of three names sharing a prefix
    "Alice Bob",      # two words: must win over "Alice" for "@Alice Bob"
    "AliceBlue",      # longer name sharing the same prefix
    "Case One",
    "case one",       # collides with the row above modulo case -> ambiguous
    "   ",            # blank once stripped -> never resolvable
    "Zeta",
]


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(DB_URL, echo=False, future=True)
    TestingSessionLocal = sessionmaker(autoflush=False, bind=engine)
    models.Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        models.Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def client(db_session):
    def _get_db_override():
        return db_session

    app.dependency_overrides[get_db] = _get_db_override
    _client = TestClient(app)
    _client.headers.update({"Authorization": f"Bearer {create_access_token(OWNER)}"})
    yield _client
    app.dependency_overrides.clear()


class Statements:
    """Statement text recorded between two points, on the session's own engine."""

    def __init__(self, engine):
        self.engine = engine
        self.records: list[str] = []

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        self.records.append(" ".join(statement.split()))

    def __enter__(self):
        self.records = []
        sa.event.listen(self.engine, "before_cursor_execute", self._before)
        return self

    def __exit__(self, *exc):
        sa.event.remove(self.engine, "before_cursor_execute", self._before)

    @property
    def total(self) -> int:
        return len(self.records)

    def reading(self, table: str) -> int:
        needle = f" from {table}"
        return sum(
            1 for s in self.records if s.upper().startswith("SELECT") and needle in s.lower()
        )


def seed(db, member_names: list[str], extra_users: list[str] = ()) -> tuple[str, dict]:
    """Owner-run workspace with one public channel and ``member_names`` members.

    Returns ``(channel_id, {display_name: user_id})``. Ids are positional so the
    controls can name a specific recipient.
    """
    tag = uuid.uuid4().hex[:6]
    if not db.query(User).filter(User.id == OWNER).first():
        db.add(User(id=OWNER, email=f"{OWNER}@example.com", display_name="Owner Zero"))
    ids: dict = {}
    for i, name in enumerate(member_names):
        uid = f"c3-m-{i}-{tag}"
        db.add(User(id=uid, email=f"{uid}@example.com", display_name=name))
        ids[name] = uid
    for i, name in enumerate(extra_users):
        db.add(User(id=f"c3-x-{i}-{tag}", email=f"c3-x-{i}-{tag}@example.com", display_name=name))
    ws = Workspace(name=f"C3 {tag}", slug=f"c3-{tag}")
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=OWNER, role="owner"))
    for uid in ids.values():
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=uid, role="member"))
    chan = Channel(workspace_id=ws.id, name="general", type="general", created_by=OWNER)
    db.add(chan)
    db.commit()
    return chan.id, ids


def post(client, channel_id: str, content: str, parent_id: str | None = None) -> str:
    payload: dict = {"content": content}
    if parent_id:
        payload["parent_id"] = parent_id
    resp = client.post(f"/channels/{channel_id}/messages", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def fanout(client, db, channel_id: str, content: str) -> list[tuple[str, str]]:
    """``(user_id, type)`` for the notifications this one message just wrote."""
    before = {r.id for r in db.query(models.Notification).all()}
    post(client, channel_id, content)
    fresh = [r for r in db.query(models.Notification).all() if r.id not in before]
    return sorted((r.user_id, r.type) for r in fresh)


# ---------------------------------------------------------------------------
# CONTROLS — who gets notified, pinned before the query shape changed
# ---------------------------------------------------------------------------


def test_control_mention_resolution_over_tricky_names(client, db_session):
    chan, ids = seed(db_session, TRICKY)

    assert fanout(client, db_session, chan, "hello @Alice Bob") == [
        (ids["Alice Bob"], "mention")
    ]
    assert fanout(client, db_session, chan, "ping @Alice") == [(ids["Alice"], "mention")]
    # A word character after the name ends the token: neither "AliceBlue" nor
    # "Alice" may claim "@AliceBlueprint".
    assert fanout(client, db_session, chan, "@AliceBlueprint here") == []
    assert fanout(client, db_session, chan, "@AliceBlue and @Alice") == sorted(
        [(ids["AliceBlue"], "mention"), (ids["Alice"], "mention")]
    )
    # Two members whose names collide modulo case are ambiguous, so nobody is.
    assert fanout(client, db_session, chan, "@Case One and @case one") == []
    assert fanout(client, db_session, chan, "yo @Zeta and @Zeta again") == [
        (ids["Zeta"], "mention")
    ]
    assert fanout(client, db_session, chan, "no mention at all") == []
    assert fanout(client, db_session, chan, "@   spaced") == []


def test_control_the_right_user_is_notified(client, db_session):
    chan, ids = seed(db_session, TRICKY)
    mid = post(client, chan, "status: @Alice Bob")
    rows = db_session.query(models.Notification).all()
    assert [(r.user_id, r.type) for r in rows] == [(ids["Alice Bob"], "mention")]
    assert rows[0].title == "Owner Zero mentioned you"
    assert rows[0].link == f"/dashboard/chat?channel={chan}"
    assert rows[0].content == "Owner Zero mentioned you in #general."
    assert mid


def test_control_non_member_with_a_matching_name_is_never_notified(client, db_session):
    chan, _ = seed(db_session, TRICKY, extra_users=["Stranger Here"])
    assert fanout(client, db_session, chan, "hey @Stranger Here") == []
    assert db_session.query(models.Notification).count() == 0


def test_control_dm_and_thread_fanout_are_untouched(client, db_session):
    chan, ids = seed(db_session, TRICKY)
    ws_id = db_session.query(Channel).filter(Channel.id == chan).first().workspace_id
    peer = ids["Zeta"]
    dm = Channel(
        workspace_id=ws_id, name=f"dm-{OWNER}-{peer}", type="dm", created_by=OWNER, is_private=True
    )
    db_session.add(dm)
    db_session.flush()
    db_session.add_all(
        [
            ChannelMember(channel_id=dm.id, user_id=OWNER),
            ChannelMember(channel_id=dm.id, user_id=peer),
        ]
    )
    db_session.commit()

    first = post(client, dm.id, "are you around?")
    assert fanout(client, db_session, chan, "@Zeta heads up") == [(peer, "mention")]

    as_peer = TestClient(app)
    as_peer.headers.update({"Authorization": f"Bearer {create_access_token(peer)}"})
    before = {r.id for r in db_session.query(models.Notification).all()}
    assert as_peer.post(
        f"/channels/{dm.id}/messages", json={"content": "yes", "parent_id": first}
    ).status_code == 201
    fresh = [r for r in db_session.query(models.Notification).all() if r.id not in before]
    # The peer's reply reaches the owner once, as a DM: the thread rule and the
    # DM rule name the same recipient, and a user is notified at most once.
    assert [(r.user_id, r.type) for r in fresh] == [(OWNER, "dm")]


# ---------------------------------------------------------------------------
# MEASUREMENT — one read of users, not one per member
# ---------------------------------------------------------------------------


def test_measured_users_reads_do_not_grow_with_membership(client, db_session):
    """One mentioning POST, 5 vs 25 members, plus the same message with no mention.

    The plain-message leg is the baseline: two reads of ``users`` that have
    nothing to do with the roster (the author for the notification title, the
    author eager-load behind the response). The mentioning leg must add exactly
    one more read, whatever the headcount.
    """
    observed = {}
    for n in (5, 25):
        names = [f"Member Number {i:02d}" for i in range(n)]
        chan, _ = seed(db_session, names)
        with Statements(db_session.get_bind()) as mentioned:
            post(client, chan, f"standup now: @{names[2]}")
        with Statements(db_session.get_bind()) as plain:
            post(client, chan, "standup now, nobody mentioned")
        observed[n] = {
            "mentioned": (mentioned.reading("users"), mentioned.total),
            "plain": (plain.reading("users"), plain.total),
        }
        print(
            f"MEASURE after(members={n}): mentioning users_selects={mentioned.reading('users')} "
            f"statements={mentioned.total} | no-mention users_selects={plain.reading('users')} "
            f"statements={plain.total}"
        )

    assert observed[5]["mentioned"] == observed[25]["mentioned"], (
        f"the mentioning POST costs {observed[5]['mentioned']} statements at 5 members and "
        f"{observed[25]['mentioned']} at 25: one SELECT per member is back"
    )
    for n in (5, 25):
        users_reads, _total = observed[n]["mentioned"]
        baseline, _ = observed[n]["plain"]
        # The author is a workspace member too, so one batched roster read can
        # serve both; the ceiling is the baseline plus the one roster statement.
        assert users_reads <= baseline + 1, (
            f"the roster must be one read of users at {n} members, got {users_reads} "
            f"against a {baseline}-read baseline for the same message without a mention"
        )


def test_measured_a_message_without_a_mention_never_reads_the_roster(client, db_session):
    """The early return is the cheapest part of this path, and it must stay."""
    observed = {}
    for n in (5, 25):
        chan, _ = seed(db_session, [f"Member Number {i:02d}" for i in range(n)])
        with Statements(db_session.get_bind()) as st:
            post(client, chan, "plain message, no at-sign")
        observed[n] = (st.reading("users"), st.total)
        print(
            f"MEASURE after(members={n}, POST without a mention): "
            f"users_selects={st.reading('users')} request_statements={st.total}"
        )
    assert observed[5] == observed[25], observed
