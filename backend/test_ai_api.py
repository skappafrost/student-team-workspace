"""Tests for AI-assist endpoints (deterministic fallback, no LLM key)."""

import pytest
from fastapi.testclient import TestClient

from app import app, Role
from conftest import as_user, clear_auth


# ---------------------------------------------------------------------------
# Auth helpers (shared, real-JWT based — see conftest.py)
# ---------------------------------------------------------------------------


def create_workspace(client: TestClient, user_id: str = "owner", name: str = "WS", slug: str = "ws"):
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": name, "slug": slug, "description": "x"})
    assert resp.status_code == 201
    return resp.json()


def create_project(client: TestClient, workspace_id: str, name: str = "Project"):
    as_user(client, "owner")
    resp = client.post(f"/workspaces/{workspace_id}/projects", json={"name": name, "description": "x"})
    assert resp.status_code == 201
    return resp.json()


def create_task(client: TestClient, project_id: str, title: str, description: str):
    as_user(client, "owner")
    resp = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": title, "description": description, "priority": "medium", "status": "todo"},
    )
    assert resp.status_code == 201
    return resp.json()


def create_page(client: TestClient, workspace_id: str, title: str, content: str):
    as_user(client, "owner")
    resp = client.post(
        f"/workspaces/{workspace_id}/pages",
        json={"title": title, "slug": title.lower().replace(" ", "-"), "content": content},
    )
    assert resp.status_code == 201
    return resp.json()


def create_channel(client: TestClient, workspace_id: str, name: str):
    as_user(client, "owner")
    resp = client.post(
        f"/workspaces/{workspace_id}/channels",
        json={"name": name, "type": "general"},
    )
    assert resp.status_code == 201
    return resp.json()


def create_message(client: TestClient, channel_id: str, content: str):
    as_user(client, "owner")
    resp = client.post(f"/channels/{channel_id}/messages", json={"content": content})
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Summarize tests
# ---------------------------------------------------------------------------

def test_summarize_task(client):
    ws = create_workspace(client, "owner")
    project = create_project(client, ws["id"])
    task = create_task(
        client,
        project["id"],
        title="Fix login bug",
        description="Users cannot log in when password contains special characters. This blocks the release.",
    )
    as_user(client, "owner")
    resp = client.post("/ai/summarize", json={"kind": "task", "ref_id": task["id"]})
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "Fix login bug" in data["summary"]


def test_summarize_page(client):
    ws = create_workspace(client, "owner")
    page = create_page(
        client,
        ws["id"],
        title="Onboarding Guide",
        content="Welcome to the team. First, set up your machine. Then install the dependencies.",
    )
    as_user(client, "owner")
    resp = client.post("/ai/summarize", json={"kind": "page", "ref_id": page["id"]})
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "Onboarding Guide" in data["summary"]


def test_summarize_channel(client):
    ws = create_workspace(client, "owner")
    channel = create_channel(client, ws["id"], "general")
    create_message(client, channel["id"], "Hello everyone, welcome to the project.")
    create_message(client, channel["id"], "The roadmap is on the wiki page for all members.")
    as_user(client, "owner")
    resp = client.post("/ai/summarize", json={"kind": "channel", "ref_id": channel["id"]})
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert channel["name"] in data["summary"]


def test_summarize_requires_auth(client):
    ws = create_workspace(client, "owner")
    project = create_project(client, ws["id"])
    task = create_task(client, project["id"], "X", "Y")
    as_user(client, "owner")
    # clear auth
    clear_auth(client)
    resp = client.post("/ai/summarize", json={"kind": "task", "ref_id": task["id"]})
    assert resp.status_code == 401


def test_summarize_unknown_kind(client):
    ws = create_workspace(client, "owner")
    as_user(client, "owner")
    resp = client.post("/ai/summarize", json={"kind": "unknown", "ref_id": "x"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------

def test_search_tasks_pages_messages_ranked(client):
    ws = create_workspace(client, "owner")
    project = create_project(client, ws["id"])
    task = create_task(client, project["id"], "Alpha task", "Contains the keyword uniquely alphaone.")
    page = create_page(client, ws["id"], "Alpha page", "Alphaone is described here in the page body.")
    channel = create_channel(client, ws["id"], "alpha-channel")
    create_message(client, channel["id"], "Message about alphaone in this channel.")

    as_user(client, "owner")
    resp = client.get("/ai/search", params={"q": "alphaone", "scope": "tasks,pages,messages"})
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    results = data["results"]
    assert len(results) == 3
    kinds = {r["kind"] for r in results}
    assert kinds == {"task", "page", "message"}


def test_search_respects_workspace_membership(client):
    ws = create_workspace(client, "owner")
    project = create_project(client, ws["id"])
    create_task(client, project["id"], "Secret task", "secret keyword s3cr3t")

    as_user(client, "owner")
    resp = client.get("/ai/search", params={"q": "s3cr3t"})
    assert resp.status_code == 200
    owner_results = resp.json()["results"]
    assert len(owner_results) == 1


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_search_requires_auth(client):
    resp = client.get("/ai/search", params={"q": "anything"})
    assert resp.status_code == 401
