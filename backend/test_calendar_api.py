"""Tests for Calendar/Event CRUD endpoints with RBAC and date-range filtering."""

import pytest
from fastapi.testclient import TestClient

from app import app, Role
from conftest import as_user, clear_auth, make_user


# ---------------------------------------------------------------------------
# Auth / helper helpers (mirrors test_projects_api)
# ---------------------------------------------------------------------------


def create_workspace(client: TestClient, user_id: str = "owner", name: str = "WS", slug: str = "ws"):
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201
    return resp.json()


def add_member(client, db_session, workspace_id, email, role, user_id):
    """Invite and accept a user into a workspace, return the new membership record."""
    owner_resp = client.post(
        f"/workspaces/{workspace_id}/invites",
        json={"email": email, "role": role},
    )
    assert owner_resp.status_code == 201, owner_resp.text
    token = owner_resp.json()["token"]

    make_user(db_session, user_id, email=email)
    clear_auth(client)
    as_user(client, user_id)
    accept_resp = client.post("/invites/accept", json={"token": token})
    assert accept_resp.status_code == 201, accept_resp.text
    return accept_resp.json()


def create_event(client, workspace_id, **overrides):
    payload = {
        "title": "Test Event",
        "description": "desc",
        "start_at": "2026-08-28T09:00:00",
        "end_at": "2026-08-28T10:00:00",
        "all_day": False,
        "event_type": "meeting",
    }
    payload.update(overrides)
    return client.post(f"/workspaces/{workspace_id}/events", json=payload)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_create_event(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = create_event(client, ws["id"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test Event"
    assert data["workspace_id"] == ws["id"]
    assert data["event_type"] == "meeting"
    assert data["all_day"] is False
    assert data["created_by"] == "owner"


def test_get_event(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    event = create_event(client, ws["id"], title="Exam Day").json()

    resp = client.get(f"/events/{event['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Exam Day"
    assert data["id"] == event["id"]


def test_update_event_by_creator(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    event = create_event(client, ws["id"]).json()

    resp = client.patch(f"/events/{event['id']}", json={"title": "Updated Title", "event_type": "exam"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Title"
    assert data["event_type"] == "exam"


def test_delete_event_by_creator(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    event = create_event(client, ws["id"]).json()

    resp = client.delete(f"/events/{event['id']}")
    assert resp.status_code == 204
    assert client.get(f"/events/{event['id']}").status_code == 404


def test_list_events_date_range_filter(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")

    # Event inside the range
    create_event(client, ws["id"], title="Inside", start_at="2026-08-28T09:00:00", end_at="2026-08-28T10:00:00")
    # Event before the range
    create_event(client, ws["id"], title="Before", start_at="2026-08-27T09:00:00", end_at="2026-08-27T10:00:00")
    # Event after the range
    create_event(client, ws["id"], title="After", start_at="2026-08-29T09:00:00", end_at="2026-08-29T10:00:00")

    resp = client.get(f"/workspaces/{ws['id']}/events?start=2026-08-28T00:00:00&end=2026-08-28T23:59:59")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Inside"


def test_all_day_event_no_end(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = create_event(
        client,
        ws["id"],
        title="All Day",
        start_at="2026-08-28T00:00:00",
        end_at=None,
        all_day=True,
        event_type="reminder",
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["all_day"] is True
    assert data["end_at"] is None
    assert data["event_type"] == "reminder"


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_member_can_create_and_view_event(client, db_session):
    ws = create_workspace(client, "owner")
    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = create_event(client, ws["id"], title="Member Event")
    assert resp.status_code == 201
    event_id = resp.json()["id"]

    assert client.get(f"/events/{event_id}").status_code == 200


def test_member_cannot_update_event_created_by_owner(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    event = create_event(client, ws["id"], title="Owner Event").json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = client.patch(f"/events/{event['id']}", json={"title": "Hacked"})
    assert resp.status_code == 403


def test_member_cannot_delete_event_created_by_owner(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    event = create_event(client, ws["id"]).json()

    add_member(client, db_session, ws["id"], "member@example.com", Role.MEMBER.value, "member-user")

    as_user(client, "member-user")
    resp = client.delete(f"/events/{event['id']}")
    assert resp.status_code == 403


def test_admin_can_update_and_delete_any_event(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    event = create_event(client, ws["id"], title="Owner Event").json()

    add_member(client, db_session, ws["id"], "admin@example.com", Role.ADMIN.value, "admin-user")

    as_user(client, "admin-user")
    update_resp = client.patch(f"/events/{event['id']}", json={"title": "Admin Updated"})
    assert update_resp.status_code == 200
    assert update_resp.json()["title"] == "Admin Updated"
    assert client.delete(f"/events/{event['id']}").status_code == 204


def test_non_member_cannot_access_event(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    event = create_event(client, ws["id"]).json()

    as_user(client, "stranger")
    resp = client.get(f"/events/{event['id']}")
    assert resp.status_code == 403


def test_guest_cannot_create_event(client, db_session):
    ws = create_workspace(client, "owner")
    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user")
    resp = create_event(client, ws["id"], title="Guest Event")
    assert resp.status_code == 403


def test_guest_cannot_view_or_modify_events(client, db_session):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    event = create_event(client, ws["id"]).json()

    add_member(client, db_session, ws["id"], "guest@example.com", Role.GUEST.value, "guest-user")

    as_user(client, "guest-user")
    assert client.get(f"/events/{event['id']}").status_code == 403
    assert client.get(f"/workspaces/{ws['id']}/events").status_code == 403
    assert client.patch(f"/events/{event['id']}", json={"title": "x"}).status_code == 403
    assert client.delete(f"/events/{event['id']}").status_code == 403
