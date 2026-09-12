#!/usr/bin/env python3
"""Load a demo-data pack (``busy-workspace.json``) into a running backend.

Stdlib only (``urllib``). Flow:

1. Login as the admin (``--email``/``--password``); register first if needed.
2. Create the pack workspace.
3. Register the 10 pack users, invite + accept each into the workspace.
4. Create projects + ~200 tasks (assignees mapped to the new users).
5. Create long chat channels + messages (round-robin authors).
6. Create sample wiki pages (parents first).
7. Re-read counts via the API, print them, assert users>=10 and tasks~=200.

Usage:
    python load-pack.py --api http://127.0.0.1:8000 --email admin@example.com --password <pw>
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PACK = HERE / "busy-workspace.json"

TASK_MIN, TASK_MAX = 195, 205  # "~200" tolerance band
MIN_MEMBERS = 10


def api(method: str, url: str, token: str | None = None,
        payload: dict | None = None, timeout: float = 15.0) -> tuple[int, object]:
    """Single JSON API call. Returns (status_code, parsed body)."""
    data = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed: object = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = {"detail": raw[:500]}
        return exc.code, parsed


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def login_or_register(base: str, email: str, password: str, timeout: float) -> tuple[str, dict]:
    """Return (token, user) for email, registering first if the account is new."""
    status, body = api("POST", f"{base}/auth/login",
                       payload={"email": email, "password": password}, timeout=timeout)
    if status == 200:
        assert isinstance(body, dict)
        return body["access_token"], body["user"]
    status, body = api("POST", f"{base}/auth/register",
                       payload={"email": email, "password": password}, timeout=timeout)
    if status == 201:
        assert isinstance(body, dict)
        return body["access_token"], body["user"]
    if status == 409:
        # Exists but login failed above: surface the original login error.
        fail(f"account {email} exists but login failed (check --password).")
    fail(f"auth failed for {email}: HTTP {status} {body}")
    raise AssertionError("unreachable")


def create_workspace(base: str, token: str, pack_ws: dict,
                     slug_suffix: str | None, timeout: float) -> dict:
    slug = pack_ws["slug"] + (f"-{slug_suffix}" if slug_suffix else "")
    payload = {"name": pack_ws["name"], "slug": slug, "description": pack_ws.get("description")}
    status, body = api("POST", f"{base}/workspaces", token=token, payload=payload, timeout=timeout)
    if status == 201:
        assert isinstance(body, dict)
        return body
    if status == 409 and not slug_suffix:
        # Slug taken (re-run against same DB): retry once with a unique suffix.
        return create_workspace(base, token, pack_ws, uuid.uuid4().hex[:6], timeout)
    fail(f"create workspace failed: HTTP {status} {body}")
    raise AssertionError("unreachable")


def count_pages_tree(nodes: list) -> int:
    total = 0
    for node in nodes:
        total += 1
        children = node.get("children") or []
        total += count_pages_tree(children)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Load busy-workspace.json into STW (stdlib only).")
    parser.add_argument("--api", required=True, help="Backend base URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("--email", required=True, help="Admin email (registered if new)")
    parser.add_argument("--password", required=True, help="Admin password")
    parser.add_argument("--pack", default=str(DEFAULT_PACK))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--slug-suffix", default=None,
                        help="Optional workspace slug suffix (auto-added on 409)")
    args = parser.parse_args()

    base = args.api.rstrip("/")
    pack = json.loads(Path(args.pack).read_text(encoding="utf-8"))

    admin_token, admin_user = login_or_register(base, args.email, args.password, args.timeout)
    print(f"admin: {admin_user['email']} (id={admin_user['id']})")

    ws = create_workspace(base, admin_token, pack["workspace"], args.slug_suffix, args.timeout)
    ws_id = ws["id"]
    print(f"workspace: {ws['name']} (slug={ws['slug']} id={ws_id})")

    # --- Users: register + invite + accept ------------------------------------
    user_tokens: list[str] = []
    user_ids: list[str] = []
    for u in pack["users"]:
        token, user = login_or_register(base, u["email"], u["password"], args.timeout)
        user_tokens.append(token)
        user_ids.append(user["id"])
        status, invite = api("POST", f"{base}/workspaces/{ws_id}/invites", token=admin_token,
                             payload={"email": u["email"], "role": u.get("role", "member")},
                             timeout=args.timeout)
        if status != 201:
            fail(f"invite {u['email']} failed: HTTP {status} {invite}")
        assert isinstance(invite, dict)
        status, _ = api("POST", f"{base}/invites/accept", token=token,
                        payload={"token": invite["token"]}, timeout=args.timeout)
        if status == 409:
            pass  # already a member (idempotent re-run)
        elif status != 201:
            fail(f"accept invite {u['email']} failed: HTTP {status}")
    print(f"users: registered={len(user_ids)}")

    # --- Projects + tasks -------------------------------------------------------
    project_ids: list[str] = []
    tasks_created = 0
    for p in pack["projects"]:
        status, proj = api("POST", f"{base}/workspaces/{ws_id}/projects", token=admin_token,
                           payload={"name": p["name"], "description": p.get("description")},
                           timeout=args.timeout)
        if status != 201:
            fail(f"create project {p['name']} failed: HTTP {status} {proj}")
        assert isinstance(proj, dict)
        project_ids.append(proj["id"])
        for t in p["tasks"]:
            status, _ = api("POST", f"{base}/projects/{proj['id']}/tasks", token=admin_token,
                            payload={
                                "title": t["title"],
                                "description": t.get("description"),
                                "status": t.get("status", "todo"),
                                "priority": t.get("priority", "medium"),
                                "assignee_id": user_ids[t["assignee_index"]] if t.get("assignee_index") is not None else None,
                                "position": t.get("position", 0.0),
                            }, timeout=args.timeout)
            if status != 201:
                fail(f"create task '{t['title']}' failed: HTTP {status}")
            tasks_created += 1
    print(f"projects: {len(project_ids)}, tasks posted: {tasks_created}")

    # --- Channels + messages ------------------------------------------------------
    author_pool = user_tokens + [admin_token]
    channel_ids: list[str] = []
    messages_posted = 0
    for ci, c in enumerate(pack["channels"]):
        status, ch = api("POST", f"{base}/workspaces/{ws_id}/channels", token=admin_token,
                         payload={"name": c["name"], "type": c.get("type", "general")},
                         timeout=args.timeout)
        if status != 201:
            fail(f"create channel {c['name']} failed: HTTP {status} {ch}")
        assert isinstance(ch, dict)
        channel_ids.append(ch["id"])
        for mi, m in enumerate(c["messages"]):
            token = author_pool[(m.get("author_index", mi)) % len(author_pool)]
            status, _ = api("POST", f"{base}/channels/{ch['id']}/messages", token=token,
                            payload={"content": m["content"]}, timeout=args.timeout)
            if status != 201:
                fail(f"post message to {c['name']} failed: HTTP {status}")
            messages_posted += 1
    print(f"channels: {len(channel_ids)}, messages posted: {messages_posted}")

    # --- Wiki pages (parents first — pack order guarantees it) ----------------------
    slug_to_id: dict[str, str] = {}
    pages_created = 0
    for pg in pack["pages"]:
        payload: dict = {"title": pg["title"], "slug": pg["slug"], "content": pg.get("content")}
        if pg.get("parent_slug"):
            parent_id = slug_to_id.get(pg["parent_slug"])
            if parent_id is None:
                fail(f"page {pg['slug']}: parent {pg['parent_slug']} not created yet")
            payload["parent_id"] = parent_id
        status, created = api("POST", f"{base}/workspaces/{ws_id}/pages", token=admin_token,
                              payload=payload, timeout=args.timeout)
        if status != 201:
            fail(f"create page {pg['slug']} failed: HTTP {status} {created}")
        assert isinstance(created, dict)
        slug_to_id[pg["slug"]] = created["id"]
        pages_created += 1
    print(f"pages: {pages_created}")

    # --- Verify counts via the API --------------------------------------------------
    _, members = api("GET", f"{base}/workspaces/{ws_id}/members", token=admin_token, timeout=args.timeout)
    _, projects = api("GET", f"{base}/workspaces/{ws_id}/projects", token=admin_token, timeout=args.timeout)
    task_total = 0
    for pid in project_ids:
        _, tasks = api("GET", f"{base}/projects/{pid}/tasks", token=admin_token, timeout=args.timeout)
        task_total += len(tasks) if isinstance(tasks, list) else 0
    _, channels = api("GET", f"{base}/workspaces/{ws_id}/channels", token=admin_token, timeout=args.timeout)
    msg_total = 0
    for cid in channel_ids:
        _, msgs = api("GET", f"{base}/channels/{cid}/messages", token=admin_token, timeout=args.timeout)
        msg_total += len(msgs) if isinstance(msgs, list) else 0
    _, pages = api("GET", f"{base}/workspaces/{ws_id}/pages", token=admin_token, timeout=args.timeout)
    page_total = count_pages_tree(pages) if isinstance(pages, list) else 0

    counts = {
        "workspace_id": ws_id,
        "workspace_slug": ws["slug"],
        "members": len(members) if isinstance(members, list) else 0,
        "projects": len(projects) if isinstance(projects, list) else 0,
        "tasks": task_total,
        "channels": len(channels) if isinstance(channels, list) else 0,
        "messages": msg_total,
        "pages": page_total,
    }
    print("counts: " + json.dumps(counts))

    ok = True
    if counts["members"] < MIN_MEMBERS:
        print(f"ASSERT FAIL: members={counts['members']} < {MIN_MEMBERS}", file=sys.stderr)
        ok = False
    if not (TASK_MIN <= counts["tasks"] <= TASK_MAX):
        print(f"ASSERT FAIL: tasks={counts['tasks']} not in [{TASK_MIN},{TASK_MAX}]", file=sys.stderr)
        ok = False
    if not ok:
        raise SystemExit(1)
    print("OK: demo pack verified (users>=10, tasks~=200)")


if __name__ == "__main__":
    main()
