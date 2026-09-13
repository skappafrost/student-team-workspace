#!/usr/bin/env python3
"""Generate a deterministic demo-data pack for QA.

Stdlib only. Emits ``busy-workspace.json`` next to this script:

- 1 workspace
- 10 users (default)
- ~200 tasks spread across project boards (default)
- long chat channels with plenty of messages
- sample wiki pages (incl. parent/child nesting)

Everything derived from ``--seed`` via ``random.Random`` so re-running with
the same seed yields identical users / projects / tasks / channels / pages
(only ``meta.generated_at`` reflects the wall clock).

Usage:
    python make-pack.py [--seed 20260912] [--users 10] [--tasks 200]
                        [--output busy-workspace.json]
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SEED = 20260912
DEFAULT_USERS = 10
DEFAULT_TASKS = 200
DEFAULT_OUTPUT = HERE / "busy-workspace.json"

# One shared throwaway password for all pack users (local QA only).
# Satisfies RegisterIn: 8-128 chars, well under the 72-byte bcrypt limit.
USER_PASSWORD = "DemoQA-2026-pass!"

# Fixed personas so emails / display names are stable across seeds.
PERSONAS = [
    ("An Nguyen", "qa-an@example.com"),
    ("Binh Tran", "qa-binh@example.com"),
    ("Chi Le", "qa-chi@example.com"),
    ("Dung Pham", "qa-dung@example.com"),
    ("Hieu Vo", "qa-hieu@example.com"),
    ("Khanh Do", "qa-khanh@example.com"),
    ("Linh Hoang", "qa-linh@example.com"),
    ("Minh Bui", "qa-minh@example.com"),
    ("Ngoc Dang", "qa-ngoc@example.com"),
    ("Phuc Ngo", "qa-phuc@example.com"),
]

EXTRA_NAMES = [
    ("Quynh Phan", "qa-quynh@example.com"),
    ("Son Ly", "qa-son@example.com"),
    ("Trang Vu", "qa-trang@example.com"),
    ("Tuan Huynh", "qa-tuan@example.com"),
    ("Vy Truong", "qa-vy@example.com"),
]

PROJECT_DEFS = [
    {
        "key": "website",
        "name": "Website Redesign",
        "description": "Marketing site refresh: landing, blog, docs theme.",
        "verbs": ["Design", "Implement", "Review", "Fix", "Prototype", "Polish", "Audit", "Migrate"],
        "objects": [
            "landing hero section", "pricing table", "blog index layout", "docs sidebar",
            "dark-mode tokens", "mobile nav drawer", "footer links", "OG images",
            "contact form validation", "sitemap + robots",
        ],
    },
    {
        "key": "exam",
        "name": "Exam Prep",
        "description": "Shared study plan for the final exams season.",
        "verbs": ["Summarize", "Drill", "Outline", "Solve", "Flashcard", "Recap", "Practice", "Schedule"],
        "objects": [
            "calculus problem set", "physics formulas sheet", "chemistry lab notes",
            "english essay outlines", "history timeline", "mock test #1",
            "mock test #2", "past-paper review", "study timetable", "group quiz session",
        ],
    },
    {
        "key": "robotics",
        "name": "Robotics Club",
        "description": "Line-follower bot build for the regional contest.",
        "verbs": ["Order", "Assemble", "Calibrate", "Test", "Solder", "Document", "Tune", "Demo"],
        "objects": [
            "motor driver boards", "IR sensor array", "chassis frame", "battery pack",
            "PID constants", "track test runs", "wiring harness", "pit-crew checklist",
            "contest rulebook notes", "sponsor thank-you post",
        ],
    },
    {
        "key": "mobile",
        "name": "Mobile App",
        "description": "Study-buddy app MVP: tasks, timer, streaks.",
        "verbs": ["Sketch", "Build", "Wire", "Test", "Fix", "Instrument", "Localize", "Release"],
        "objects": [
            "onboarding flow", "task list screen", "pomodoro timer", "streak widget",
            "push reminders", "offline cache", "settings page", "app icon set",
            "beta feedback form", "store listing draft",
        ],
    },
]

STATUSES = ["backlog", "todo", "doing", "done"]
STATUS_WEIGHTS = [15, 35, 25, 25]
PRIORITIES = ["low", "medium", "high", "urgent"]
PRIORITY_WEIGHTS = [30, 40, 20, 10]

CHANNEL_DEFS = [
    {"name": "general", "type": "general", "topic": "Whole-team announcements and chatter."},
    {"name": "study-group", "type": "general", "topic": "Daily study check-ins and questions."},
    {"name": "project-updates", "type": "project", "topic": "Build progress, demos, blockers."},
]
MESSAGES_PER_CHANNEL = 45

CHAT_TEMPLATES = [
    "Morning check-in: today I am working on '{task}'. Anyone blocked?",
    "Just finished '{task}' — leaving notes in the thread, please review 🙏",
    "Heads up: '{task}' is trickier than expected, might spill to tomorrow.",
    "Can someone pair with me on '{task}' after lunch?",
    "Demo went well! '{task}' got good feedback from the group.",
    "Reminder: mock review for '{task}' is this Friday, don't forget.",
    "Pushed a draft for '{task}'. Screenshots in the wiki page.",
    "Quick poll: should we split '{task}' into smaller chunks?",
    "Blocked on '{task}' — waiting for the sensor parts to arrive.",
    "Celebrating a small win: '{task}' moved to done ✅",
]

PAGE_DEFS = [
    {
        "title": "Welcome to the Busy Workspace",
        "slug": "welcome",
        "parent_slug": None,
        "content": (
            "# Welcome 👋\n\nThis is a seeded QA workspace with realistic volume: "
            "10 teammates, ~200 tasks across 4 project boards, long chat "
            "channels, and this mini wiki.\n\n## Where to look\n\n- **Projects** for the kanban boards\n"
            "- **Channels** for chat history\n- **Wiki** (you are here) for docs\n\n> Generated by `scripts/demo-packs/make-pack.py`. "
            "Safe to delete and re-import."
        ),
    },
    {
        "title": "Coding Standards",
        "slug": "coding-standards",
        "parent_slug": "welcome",
        "content": (
            "# Coding Standards\n\n1. Small PRs (< 300 lines) with a how-to-verify section.\n"
            "2. Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`.\n"
            "3. No secrets in the repo — use `.env` + `.env.example`.\n"
            "4. Green CI before requesting review.\n"
        ),
    },
    {
        "title": "Onboarding Checklist",
        "slug": "onboarding",
        "parent_slug": "welcome",
        "content": (
            "# Onboarding Checklist\n\n- [ ] Accept the workspace invite\n- [ ] Introduce yourself in #general\n"
            "- [ ] Pick one `todo` task from Website Redesign\n- [ ] Open your first draft PR\n- [ ] Book a 15-min intro call with the team\n"
        ),
    },
    {
        "title": "Study Guide",
        "slug": "study-guide",
        "parent_slug": None,
        "content": (
            "# Study Guide\n\nWeekly rhythm: 3 focused blocks per day, one mock test "
            "per weekend. Track everything on the **Exam Prep** board.\n\n"
            "## Resources\n\n- Past papers folder (ask An for access)\n- Formula sheets in the wiki children pages\n"
        ),
    },
    {
        "title": "Exam Checklist",
        "slug": "exam-checklist",
        "parent_slug": "study-guide",
        "content": (
            "# Exam Checklist\n\n- [ ] ID card + pens packed\n- [ ] Calculator batteries checked\n"
            "- [ ] Sleep before 23:00 the night before\n- [ ] Arrive 30 minutes early\n"
        ),
    },
    {
        "title": "Meeting Notes",
        "slug": "meeting-notes",
        "parent_slug": None,
        "content": (
            "# Meeting Notes\n\n## 2026-09-10 — Sprint kickoff\n\n- Agreed: demo every Friday 16:00.\n"
            "- Robotics parts budget approved.\n- Next: split the mobile-app MVP into v0.1 / v0.2.\n"
        ),
    },
]


def build_pack(seed: int = DEFAULT_SEED, n_users: int = DEFAULT_USERS,
               n_tasks: int = DEFAULT_TASKS) -> dict:
    rng = random.Random(seed)

    personas = list(PERSONAS)
    if n_users > len(personas):
        personas += EXTRA_NAMES * ((n_users - len(personas)) // len(EXTRA_NAMES) + 1)
    users = []
    for i in range(n_users):
        display_name, email = personas[i % len(personas)]
        if i >= len(PERSONAS):
            # Keep emails unique when extending past the fixed personas.
            local, domain = email.split("@")
            email = f"{local}-{i}@example.com".replace("..", ".")
        users.append({
            "display_name": display_name,
            "email": email,
            "password": USER_PASSWORD,
            # First user joins as admin for QA variety; the rest are members.
            "role": "admin" if i == 0 else "member",
        })

    # --- Tasks across boards -------------------------------------------------
    per_project, remainder = divmod(n_tasks, len(PROJECT_DEFS))
    task_pool_titles: list[str] = []
    projects = []
    for pi, pdef in enumerate(PROJECT_DEFS):
        count = per_project + (1 if pi < remainder else 0)
        tasks = []
        for ti in range(count):
            verb = rng.choice(pdef["verbs"])
            obj = rng.choice(pdef["objects"])
            title = f"{verb} {obj} #{ti + 1:02d}"
            task_pool_titles.append(title)
            tasks.append({
                "title": title,
                "description": f"QA seed: {pdef['name']} — {obj} (item {ti + 1}/{count}).",
                "status": rng.choices(STATUSES, weights=STATUS_WEIGHTS, k=1)[0],
                "priority": rng.choices(PRIORITIES, weights=PRIORITY_WEIGHTS, k=1)[0],
                "assignee_index": rng.randrange(n_users),
                "position": float(ti * 10),
            })
        projects.append({
            "key": pdef["key"],
            "name": pdef["name"],
            "description": pdef["description"],
            "tasks": tasks,
        })

    # --- Long channels --------------------------------------------------------
    channels = []
    for ci, cdef in enumerate(CHANNEL_DEFS):
        messages = []
        for mi in range(MESSAGES_PER_CHANNEL):
            template = rng.choice(CHAT_TEMPLATES)
            ref = rng.choice(task_pool_titles)
            messages.append({
                "author_index": (ci * 7 + mi * 3) % n_users,
                "content": template.format(task=ref),
            })
        channels.append({
            "name": cdef["name"],
            "type": cdef["type"],
            "topic": cdef["topic"],
            "messages": messages,
        })

    # --- Wiki pages ------------------------------------------------------------
    pages = [
        {
            "title": p["title"],
            "slug": p["slug"],
            "parent_slug": p["parent_slug"],
            "content": p["content"],
        }
        for p in PAGE_DEFS
    ]

    total_messages = sum(len(c["messages"]) for c in channels)
    pack = {
        "meta": {
            "generator": "scripts/demo-packs/make-pack.py",
            "seed": seed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "users": len(users),
                "projects": len(projects),
                "tasks": sum(len(p["tasks"]) for p in projects),
                "channels": len(channels),
                "messages": total_messages,
                "pages": len(pages),
            },
        },
        "workspace": {
            "name": "Busy Workspace (demo)",
            "slug": "busy-workspace-demo",
            "description": "Seeded QA workspace: 10 teammates, ~200 tasks, long channels, sample wiki.",
        },
        "users": users,
        "projects": projects,
        "channels": channels,
        "pages": pages,
    }
    return pack


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate busy-workspace.json demo pack (stdlib only).")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--tasks", type=int, default=DEFAULT_TASKS)
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    pack = build_pack(seed=args.seed, n_users=args.users, n_tasks=args.tasks)
    out = Path(args.output)
    out.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    c = pack["meta"]["counts"]
    print(f"Wrote {out} (seed={args.seed}): "
          f"{c['users']} users, {c['projects']} projects, {c['tasks']} tasks, "
          f"{c['channels']} channels, {c['messages']} messages, {c['pages']} pages")


if __name__ == "__main__":
    main()
