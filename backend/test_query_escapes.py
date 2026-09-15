"""TA3-2: ilike wildcard escaping + channel type enum validation.

Search endpoints must treat ``%`` and ``_`` in user input as LITERAL
characters, not SQL LIKE wildcards (a page titled "Tiến độ 50%" must be
found by searching "50%", and searching "5_0" must NOT match it). Channel
creation must reject unknown channel types with 422 at the schema layer.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import Base, Role, app, create_access_token
from models import User, WorkspaceMembership


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine("sqlite:///./test_stw_esc.db", echo=False)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def _get_db_override():
        return db_session

    from database import get_db

    app.dependency_overrides[get_db] = _get_db_override
    _client = TestClient(app)
    _client._db = db_session
    yield _client
    app.dependency_overrides.clear()


def as_user(client: TestClient, user_id: str, role: str = Role.OWNER.value):
    db = getattr(client, "_db", None)
    if db is not None and not db.query(User).filter(User.id == user_id).first():
        db.add(User(id=user_id, email=f"{user_id}@example.com", display_name=user_id))
        db.commit()
    client.headers["Authorization"] = f"Bearer {create_access_token(user_id)}"


@pytest.fixture(scope="function")
def ws_id(client, db_session):
    db_session.add(User(id="u1", email="u1@example.com", display_name="Owner One"))
    db_session.commit()
    as_user(client, "u1")
    wid = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()["id"]
    return wid


# ---------------------------------------------------------------------------
# 1. Page search (GET /workspaces/{id}/pages?search=...) — % and _ are literal
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def pct_pages(client, ws_id):
    """Pages exercising literal '%' and '_' in titles."""
    client.post(
        f"/workspaces/{ws_id}/pages",
        json={"title": "Tiến độ 50% hoàn thành", "slug": "pct-page"},
    )
    client.post(
        f"/workspaces/{ws_id}/pages",
        json={"title": "Báo cáo giai đoạn 2_2", "slug": "underscore-page"},
    )
    client.post(
        f"/workspaces/{ws_id}/pages",
        json={"title": "Báo cáo chung", "slug": "plain-page"},
    )
    # 'AxB' exists so a wildcard '_' search for 'A_B' can be caught matching it.
    client.post(
        f"/workspaces/{ws_id}/pages",
        json={"title": "roadmap AxB planning", "slug": "axb-page"},
    )
    # '50 dollars off' exists so a wildcard '%' search for '50%' can be caught
    # matching it (raw pattern '%50%%' ends with wildcard % matching everything
    # after '50').
    client.post(
        f"/workspaces/{ws_id}/pages",
        json={"title": "50 dollars off", "slug": "fifty-off-page"},
    )


def test_page_search_finds_literal_percent(pct_pages, client, ws_id):
    """Searching '50%' must find the page whose title literally contains 50%."""
    res = client.get(f"/workspaces/{ws_id}/pages", params={"search": "50%"})
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()]
    assert any("50%" in t for t in titles)
    # ...and it must NOT drag in pages that merely contain '50' without the
    # literal '%' (raw '%50%%' would match '50 dollars off' too).
    assert "50 dollars off" not in titles


def test_page_search_percent_is_not_wildcard(pct_pages, client, ws_id):
    """'50%2' must not match anything: no page contains a literal '50%2', and
    after escaping the inner % is literal. With raw wildcards, '%50%2%' could
    only match if some title had '50' then '2' later — none does; the sharp
    false-positive case is covered by test_page_search_finds_literal_percent."""
    res = client.get(f"/workspaces/{ws_id}/pages", params={"search": "50%2"})
    assert res.status_code == 200
    assert res.json() == []


def test_page_search_underscore_is_not_wildcard(pct_pages, client, ws_id):
    """'_' must be literal: '2_2' matches only the page with literal '2_2';
    'A_B' must NOT match the page titled 'AxB' (wildcard _ would)."""
    res = client.get(f"/workspaces/{ws_id}/pages", params={"search": "2_2"})
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()]
    assert titles == ["Báo cáo giai đoạn 2_2"]

    res = client.get(f"/workspaces/{ws_id}/pages", params={"search": "A_B"})
    assert res.status_code == 200
    assert res.json() == []  # 'AxB' must not match a literal 'A_B' search

    res = client.get(f"/workspaces/{ws_id}/pages", params={"search": "2_3"})
    assert res.status_code == 200
    assert res.json() == []


def test_page_search_plain_term_still_matches(pct_pages, client, ws_id):
    """Happy path unchanged: plain search terms still find pages (case-insensitive)."""
    res = client.get(f"/workspaces/{ws_id}/pages", params={"search": "báo cáo"})
    assert res.status_code == 200
    assert len(res.json()) == 2  # 'Báo cáo giai đoạn 2_2' + 'Báo cáo chung'


def test_page_search_lone_percent_matches_only_percent_titles(pct_pages, client, ws_id):
    """Searching a bare '%' must only return pages that literally contain '%'
    — not the whole workspace (raw wildcard % would dump everything)."""
    res = client.get(f"/workspaces/{ws_id}/pages", params={"search": "%"})
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()]
    assert titles == ["Tiến độ 50% hoàn thành"]


def test_page_search_lone_underscore_matches_only_underscore_titles(
    pct_pages, client, ws_id
):
    """Searching a bare '_' must only return pages that literally contain '_'."""
    res = client.get(f"/workspaces/{ws_id}/pages", params={"search": "_"})
    assert res.status_code == 200
    titles = [p["title"] for p in res.json()]
    assert titles == ["Báo cáo giai đoạn 2_2"]


# ---------------------------------------------------------------------------
# 2. Message search (GET /channels/{id}/messages?q=...)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def channel_with_messages(client, ws_id, db_session):
    db_session.add(
        WorkspaceMembership(
            workspace_id=ws_id, user_id="u2", role=Role.MEMBER.value
        )
    )
    db_session.commit()
    as_user(client, "u1")
    ch = client.post(
        f"/workspaces/{ws_id}/channels", json={"name": "search-me", "type": "general"}
    ).json()
    for content in [
        "Kế hoạch đạt 100% vào tuần sau",
        "Task 3_1 đã xong",
        "Cuộc họp lúc 9h",
        "roadmap AxB planning",
        "5 dollars saved",
    ]:
        r = client.post(f"/channels/{ch['id']}/messages", json={"content": content})
        assert r.status_code == 201, r.text
    return ch["id"]


def test_message_search_finds_literal_percent(channel_with_messages, client, ws_id):
    ch_id = channel_with_messages
    res = client.get(f"/channels/{ch_id}/messages", params={"q": "100%"})
    assert res.status_code == 200
    contents = [m["content"] for m in res.json()]
    assert any("100%" in c for c in contents)
    # ...but not messages that merely contain '100' (raw '%100%%' would
    # also match '100 dollars'-style text — here '5 dollars saved' guards
    # the '5%' analogue below).
    assert all("100%" in c for c in contents)


def test_message_search_percent_not_wildcard(channel_with_messages, client):
    ch_id = channel_with_messages
    # '5% saved' is not a literal substring of any message ('5 dollars saved'
    # has '5 d...' after the 5). Only a wildcard % would match it.
    res = client.get(f"/channels/{ch_id}/messages", params={"q": "5% saved"})
    assert res.status_code == 200
    assert res.json() == []


def test_message_search_underscore_is_not_wildcard(channel_with_messages, client):
    ch_id = channel_with_messages
    res = client.get(f"/channels/{ch_id}/messages", params={"q": "3_1"})
    assert res.status_code == 200
    contents = [m["content"] for m in res.json()]
    assert contents == ["Task 3_1 đã xong"]

    # 'A_B' must not match 'AxB' (wildcard _ would).
    res = client.get(f"/channels/{ch_id}/messages", params={"q": "A_B"})
    assert res.status_code == 200
    assert res.json() == []

    # '3_2' must match nothing.
    res = client.get(f"/channels/{ch_id}/messages", params={"q": "3_2"})
    assert res.status_code == 200
    assert res.json() == []


def test_message_search_lone_percent_matches_only_percent_messages(
    channel_with_messages, client
):
    """Searching a bare '%' must only return messages literally containing '%'."""
    ch_id = channel_with_messages
    res = client.get(f"/channels/{ch_id}/messages", params={"q": "%"})
    assert res.status_code == 200
    contents = [m["content"] for m in res.json()]
    assert contents == ["Kế hoạch đạt 100% vào tuần sau"]


def test_message_search_lone_underscore_matches_only_underscore_messages(
    channel_with_messages, client
):
    """Searching a bare '_' must only return messages literally containing '_'."""
    ch_id = channel_with_messages
    res = client.get(f"/channels/{ch_id}/messages", params={"q": "_"})
    assert res.status_code == 200
    contents = [m["content"] for m in res.json()]
    assert contents == ["Task 3_1 đã xong"]


# ---------------------------------------------------------------------------
# 3. Audit-log search (GET /workspaces/{id}/audit-log?q=...) — admin-only
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def audit_ws(client, db_session):
    db_session.add(User(id="u1", email="u1@example.com", display_name="Owner One"))
    db_session.add(User(id="u2", email="u2@example.com", display_name="Member Two"))
    db_session.commit()
    as_user(client, "u1")
    wid = client.post("/workspaces", json={"name": "WS", "slug": "ws"}).json()["id"]
    db_session.add(
        WorkspaceMembership(workspace_id=wid, user_id="u2", role=Role.MEMBER.value)
    )
    db_session.commit()
    # Two pages create audit entries: one label contains a literal '%',
    # the other a literal '_'.
    client.post(
        f"/workspaces/{wid}/pages",
        json={"title": "Dự án 50% milestone", "slug": "pct-audit"},
    )
    client.post(
        f"/workspaces/{wid}/pages",
        json={"title": "Dự án 2_2 phase", "slug": "underscore-audit"},
    )
    return wid


def test_audit_log_search_finds_literal_percent(audit_ws, client):
    as_user(client, "u1")  # owner can view audit log
    res = client.get(f"/workspaces/{audit_ws}/audit-log", params={"q": "50%"})
    assert res.status_code == 200
    labels = [e["target_label"] for e in res.json()]
    assert any("50%" in (lbl or "") for lbl in labels)


def test_audit_log_search_percent_not_wildcard(audit_ws, client):
    as_user(client, "u1")
    # '0%mile' (no space) is NOT a literal substring of 'Dự án 50% milestone'
    # — the '%' there is followed by ' milestone'. Only a raw wildcard '%'
    # would match (wildcard eating '% ' before 'mile'). After escaping, this
    # must find nothing.
    res = client.get(f"/workspaces/{audit_ws}/audit-log", params={"q": "0%mile"})
    assert res.status_code == 200
    assert res.json() == []


def test_audit_log_search_finds_literal_percent_substring(audit_ws, client):
    as_user(client, "u1")
    # '0% mile' (with space) IS a literal substring of '50% milestone'.
    res = client.get(f"/workspaces/{audit_ws}/audit-log", params={"q": "0% mile"})
    assert res.status_code == 200
    labels = [e["target_label"] for e in res.json()]
    assert any("50%" in (lbl or "") for lbl in labels)


def test_audit_log_search_underscore_not_wildcard(audit_ws, client):
    as_user(client, "u1")
    res = client.get(f"/workspaces/{audit_ws}/audit-log", params={"q": "2_2"})
    assert res.status_code == 200
    labels = [e["target_label"] for e in res.json()]
    assert any("2_2" in (lbl or "") for lbl in labels)

    # '2_3' must match nothing.
    res = client.get(f"/workspaces/{audit_ws}/audit-log", params={"q": "2_3"})
    assert res.status_code == 200
    assert res.json() == []


def test_audit_log_search_lone_percent(audit_ws, client):
    as_user(client, "u1")
    res = client.get(f"/workspaces/{audit_ws}/audit-log", params={"q": "%"})
    assert res.status_code == 200
    labels = [e["target_label"] for e in res.json()]
    assert labels == ["Dự án 50% milestone"]


def test_audit_log_search_lone_underscore(audit_ws, client):
    as_user(client, "u1")
    res = client.get(f"/workspaces/{audit_ws}/audit-log", params={"q": "_"})
    assert res.status_code == 200
    labels = [e["target_label"] for e in res.json()]
    assert labels == ["Dự án 2_2 phase"]


# ---------------------------------------------------------------------------
# 4. Channel type validation (POST /workspaces/{id}/channels)
# ---------------------------------------------------------------------------

def test_channel_create_rejects_bogus_type(client, ws_id):
    """Unknown channel type must be rejected at the schema layer with 422."""
    res = client.post(
        f"/workspaces/{ws_id}/channels", json={"name": "bogus", "type": "super-bogus"}
    )
    assert res.status_code == 422


def test_channel_create_accepts_known_types(client, ws_id):
    """Happy path unchanged: all three known types still create channels."""
    for type_ in ("general", "project", "private"):
        res = client.post(
            f"/workspaces/{ws_id}/channels",
            json={"name": f"chan-{type_}", "type": type_},
        )
        assert res.status_code == 201, res.text
        assert res.json()["type"] == type_


def test_channel_create_default_type_is_general(client, ws_id):
    """Happy path unchanged: omitted type still defaults to 'general'."""
    res = client.post(f"/workspaces/{ws_id}/channels", json={"name": "default-type"})
    assert res.status_code == 201
    assert res.json()["type"] == "general"
