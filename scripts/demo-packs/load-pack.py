#!/usr/bin/env python3
"""Load a demo-data pack (``busy-workspace.json``) into a running backend.

Stdlib only (``urllib``). Flow:

1. Login as the admin (``--email``/``--password``); register first if needed.
2. Create the pack workspace.
3. Register the 10 pack users, invite + accept each into the workspace.
4. Create projects + ~200 tasks (assignees mapped to the new users).
5. Create long chat channels + messages (round-robin authors).
6. Create sample wiki pages (parents first).
7. Re-read counts via the API, print them, and assert every one equals the pack.

The backend rate-limits its own writes (``backend/rate_limit.py``: 120/min per
identity per route group, 10 logins/min per IP) and one pack load posts 200
tasks as a single identity, so a load *is* expected to be throttled. A 429 here
is a schedule, not an error: the request is re-sent after the server's own
``Retry-After`` until it fits, up to ``--max-retry-wait`` in total. The run
prints its request plan up front and its request/retry/wait totals at the end.

Usage:
    python load-pack.py --api http://127.0.0.1:8000 --email admin@example.com --password <pw>

To skip the waiting entirely, run the target with ``RATELIMIT_ENABLED=0`` (see
``scripts/demo-packs/README.md``); the loader itself never asks the server to
turn its limiter off.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import NoReturn

HERE = Path(__file__).resolve().parent
DEFAULT_PACK = HERE / "busy-workspace.json"

#: Ceiling on how long one run may spend waiting out rate limits in total.
DEFAULT_MAX_RETRY_WAIT = 600.0
#: Set from ``--max-retry-wait`` by ``main()``; see :func:`api`.
MAX_WAIT = DEFAULT_MAX_RETRY_WAIT
#: A 429 with no (or an unparseable) Retry-After header is retried after this.
RETRY_FALLBACK_WAIT = 1.0
#: Retries per request, so a server that limits forever cannot hang the loader.
MAX_RETRIES_PER_REQUEST = 40

#: Mirror of ``backend/rate_limit.py`` — used only to describe the plan before
#: the run starts, never to decide anything. If those constants change there,
#: the estimate is off but the load is still correct, because the loader follows
#: the server's Retry-After rather than its own copy of the rules.
WRITE_LIMIT = (120, 60)
LOGIN_IP_LIMIT = (10, 60)

STATS: dict = {"requests": 0, "retried": 0, "waited": 0.0}


def _request(method: str, url: str, token: str | None = None,
             payload: dict | None = None,
             timeout: float = 15.0) -> tuple[int, object, float]:
    """One JSON API call. Returns (status_code, parsed body, retry_after_secs)."""
    data = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    retry_after = 0.0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body else None), retry_after
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed: object = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = {"detail": raw[:500]}
        header = exc.headers.get("Retry-After") if exc.headers else None
        try:
            retry_after = float(header) if header else 0.0
        except (TypeError, ValueError):
            retry_after = 0.0
        return exc.code, parsed, retry_after


def api(method: str, url: str, token: str | None = None,
        payload: dict | None = None, timeout: float = 15.0,
        max_wait: float | None = None) -> tuple[int, object]:
    """``_request`` with the server's rate limit waited out instead of obeyed.

    Only 429 is retried, and only until ``max_wait`` seconds of waiting have
    accumulated across the run: a pack load that is genuinely refused returns the
    refusal so the caller's existing ``fail()`` path still reports it. Every
    other status is passed through untouched, so a 401/409/422/500 is still the
    fatal error it has always been.
    """
    budget = MAX_WAIT if max_wait is None else max_wait
    attempt = 0
    while True:
        status, body, retry_after = _request(method, url, token, payload, timeout)
        STATS["requests"] += 1
        if status != 429:
            return status, body
        attempt += 1
        wait = retry_after if retry_after > 0 else RETRY_FALLBACK_WAIT
        if attempt > MAX_RETRIES_PER_REQUEST or STATS["waited"] + wait > budget:
            print(
                f"rate limited: {method} {url} refused after {attempt} attempt(s), "
                f"{STATS['waited']:.0f}s waited of the {budget:.0f}s budget — "
                f"raise --max-retry-wait or start the server with RATELIMIT_ENABLED=0",
                file=sys.stderr,
            )
            return status, body
        STATS["retried"] += 1
        STATS["waited"] += wait
        print(
            f"rate limited: {method} {url} -> 429, waiting {wait:.0f}s "
            f"(retry {attempt}, {STATS['waited']:.0f}s of {budget:.0f}s used)",
            flush=True,
        )
        time.sleep(wait)


def describe_plan(pack: dict, identity_count: int) -> str:
    """What this run is about to do, in the units the limiter thinks in."""
    tasks = sum(len(p["tasks"]) for p in pack["projects"])
    messages = sum(len(c["messages"]) for c in pack["channels"])
    users = len(pack["users"])
    projects = len(pack["projects"])
    channels = len(pack["channels"])
    pages = len(pack["pages"])

    writes = {
        "tasks": (tasks, 1),
        "messages": (messages, identity_count),
        "invites": (users, 1),
        "projects": (projects, 1),
        "channels": (channels, 1),
        "pages": (pages, 1),
    }
    # Writes land on one bucket per (identity, route group); the busiest identity
    # in each group is what overflows, and it overflows in whole windows.
    windows = {}
    for group, (count, identities) in writes.items():
        busiest = math.ceil(count / max(identities, 1))
        needed = max(0, math.ceil(busiest / WRITE_LIMIT[0]) - 1)
        if needed:
            windows[group] = needed
    login_group = users + 1
    login_windows = max(0, math.ceil(login_group / LOGIN_IP_LIMIT[0]) - 1)
    if login_windows:
        windows["login"] = login_windows

    requests = (
        2 * login_group + 1 + 2 * users + projects + tasks
        + channels + messages + pages
        + 4 + projects + channels  # the re-read that verifies the counts
    )
    wait_groups = ", ".join(
        f"{group}: {n} x {WRITE_LIMIT[1] if group != 'login' else LOGIN_IP_LIMIT[1]}s window"
        for group, n in sorted(windows.items())
    )
    estimate = sum(
        n * (LOGIN_IP_LIMIT[1] if group == "login" else WRITE_LIMIT[1])
        for group, n in windows.items()
    )
    return (
        f"{requests} requests, {sum(writes[g][0] for g in writes)} of them writes"
        f" (busiest bucket: tasks {tasks} from 1 identity against "
        f"{WRITE_LIMIT[0]} per {WRITE_LIMIT[1]}s)"
        + (f"; expects to be throttled — {wait_groups}, so ~{estimate}s of waiting"
           if windows else "; expected to fit inside one limiter window")
    )


def print_stats(prefix: str = "summary") -> None:
    print(
        f"{prefix}: requests={STATS['requests']} rate-limit retries={STATS['retried']} "
        f"waited={STATS['waited']:.1f}s"
    )


def fail(msg: str) -> NoReturn:
    print_stats("aborted")
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
    parser.add_argument("--max-retry-wait", type=float, default=DEFAULT_MAX_RETRY_WAIT,
                        help="Total seconds this run may spend waiting out HTTP 429 "
                             "(default %(default)s). The pack load is rate-limited by "
                             "design; raise this if the estimate printed at start is "
                             "higher than the budget.")
    args = parser.parse_args()

    global MAX_WAIT
    MAX_WAIT = args.max_retry_wait
    STATS.update({"requests": 0, "retried": 0, "waited": 0.0})

    base = args.api.rstrip("/")
    pack = json.loads(Path(args.pack).read_text(encoding="utf-8"))
    print(f"plan: {describe_plan(pack, len(pack['users']) + 1)} against {base}")

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
    print_stats("run")

    # Every row the loader posted must be back. The old check was a tolerance
    # band around the shipped pack (tasks 195..205, members >= 10), which a
    # smaller pack cannot satisfy and which let a short load pass unnoticed —
    # rate-limited writes used to be exactly that.
    expected = {
        "members": len(pack["users"]) + 1,  # the pack users plus the admin
        "projects": len(pack["projects"]),
        "tasks": sum(len(p["tasks"]) for p in pack["projects"]),
        "channels": len(pack["channels"]),
        "messages": sum(len(c["messages"]) for c in pack["channels"]),
        "pages": count_pages_tree(pack["pages"]),
    }
    missing = {k: (counts[k], v) for k, v in expected.items() if counts[k] != v}
    if missing:
        for key, (got, want) in missing.items():
            print(f"ASSERT FAIL: {key}={got} want {want}", file=sys.stderr)
        raise SystemExit(1)
    print("OK: demo pack verified (" + ", ".join(f"{k}={v}" for k, v in expected.items()) + ")")


if __name__ == "__main__":
    main()
