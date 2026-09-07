# STW — Session Context Handoff

> **Project:** Student Team Workspace (STW)
> **Root:** `C:\Users\Ha Trung\Documents\Team-workspace`
> **Repo (git):** `C:\Users\Ha Trung\Documents\Team-workspace\app`
> **Backend (not a git repo):** `C:\Users\Ha Trung\Documents\Team-workspace\backend`
> **Kanban board:** `stw`
> **Handoff date:** 2026-08-31
> **Current state:** W0–W5 done, ready to seed W6

---

## 1. What this project is

A unified student-team workspace combining Notion + Discord + Trello + Drive + AI into one web app.

- **Frontend:** Next.js 16 + React 19 + TypeScript 5.7 strict + Tailwind CSS v4 + shadcn/ui
- **Backend:** FastAPI 0.141 + SQLAlchemy 2.0 + Alembic + PostgreSQL 16 + JWT (bcrypt)
- **Package manager:** Bun (preferred) or npm
- **Kanban board:** `stw` (Hermes kanban)

---

## 2. Repository layout (critical)

| Path | Purpose |
|---|---|
| `app/` | Real git repository. Frontend Next.js app. |
| `backend/` | FastAPI backend. **NOT a git repo.** |
| `Team-workspace/` root | Not a git repo. Holds docs, L1 plan, AGENTS.md, DECISIONS.md, PROJECT-STATUS.md. |

Do NOT run `git init` at root. If a stray `.git/` appears, it is accidental and must be removed/renamed.

---

## 3. Current wave status (verified)

| Wave | Status | Key evidence |
|---|---|---|
| W0 | Done | Repo scaffold, DECISIONS.md, AGENTS.md |
| W1 | Done | App shell, dark mode, Linear-style sidebar |
| W2 | Done | FastAPI + PostgreSQL schema v1, JWT auth, workspace/members |
| W3 | Done | Projects + Kanban board UI + API wiring, QA gate 12/12 E2E pass |
| W4 | Done | Fix dialog hydration, kanban API proxy, task detail panel, calendar API + UI |
| **W5** | **Done — 31/08/2026** | Chat channels/messages + WebSocket realtime + QA gate |

### W5 details (latest)

- Backend pytest: **102 passed**
- App typecheck: pass
- App build: pass
- QA report: `app/w5-qa-report.md`
- App commits on `main`:
  - `45b31c8` W5-5: chat QA gate report
  - `123feba` W5-3: wire chat UI to channels API
  - `4e7ec12` W5-4: WebSocket realtime broadcast for chat
  - `6ec2966` W5-2: chat UI page with channel/message panes

### Kanban board state

```
done: 66
archived: 43
running: 0
blocked: 0
ready: 0
todo: 0
```

---

## 4. How to verify work (run these before claiming done)

### Frontend

```bash
cd C:/Users/Ha Trung/Documents/Team-workspace/app
bun run typecheck   # tsc --noEmit
bun run build       # next build
```

### Backend

```bash
cd C:/Users/Ha Trung/Documents/Team-workspace/backend
.venv/Scripts/python.exe -m pytest -q
```

### Backend dev server

```bash
cd C:/Users/Ha Trung/Documents/Team-workspace/backend
.venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

### Frontend dev server

```bash
cd C:/Users/Ha Trung/Documents/Team-workspace/app
bun run dev         # http://localhost:3000
```

---

## 5. Zero native design rule (enforced)

Every visual effect, animation, transition, button, text treatment, or layout flourish must come from an online source/library (shadcn/ui, Tailwind UI, Origin UI, Tremor, Framer Motion, CodePen, CDN, etc.).

- Agents may only modify, adapt, or compose external assets.
- No agent may design anything from scratch — not even a single button.
- Every UI task must name its source in the task body.
- See `AGENTS.md` and `DECISIONS.md` for full rule.

---

## 6. Known follow-up issues from W5

1. **Message author UUID display** — bubbles show `author_id` UUID instead of display name. Backend should return author display name, or frontend should map via `/users/{id}`.
2. **WebSocket dev cookie-domain footgun** — when `NEXT_PUBLIC_API_URL` points to `http://127.0.0.1:8000`, WebSocket is cross-origin and the browser does not send the `session_token` cookie. Use `http://localhost:8000` for local dev to keep WebSocket same-origin.
3. **No create-channel UI** — channels are currently created via API/backend seed. Add a "Create channel" dialog/button later if needed.

---

## 7. Important Hermes kanban quirks

- `hermes kanban --board stw list` sometimes hangs. Use direct SQLite queries on `C:\Users\Ha Trung\AppData\Local\hermes\kanban\boards\stw\kanban.db` if needed.
- Worker sessions bind `HERMES_KANBAN_RUN_ID`. If a task is stuck due to dead worker/claim, use:
  ```bash
  hermes kanban --board stw reclaim <task_id>
  hermes kanban --board stw dispatch --max 2
  ```
- Valid task statuses: `triage`, `running`, `done`, `archived`. There is no `ready` in the DB enum; `ready` is a display label for `triage` with satisfied dependencies.
- `--board stw` must come **before** the subcommand.

---

## 8. Assignee role map

| Work type | Assignee |
|---|---|
| Backend, DB, API, auth, infra | `vex_agent` |
| UI adaptation, visual QA, QA gate | `zen_agent` |
| Security review | `nexus_agent` |

---

## 9. Model pin

Current pinned model for kanban tasks:

- **ID:** `alic/kimi-2.7-code`
- **Provider:** `vilao-ai`
- **Max runtime:** 2h/task

---

## 10. Next wave: W6 — Knowledge Base (markdown wiki)

Planned scope (from L1 plan):

- Backend: `Page` / `Wiki` model + CRUD API + RBAC + hierarchical parent/child pages.
- Frontend: `/dashboard/wiki` page, editor component (use a sourced markdown editor like `@uiw/react-md-editor` or ` Novel` or similar), page tree sidebar, viewer.
- Wire through Next API proxy (same pattern as tasks/channels).
- QA gate: create/edit/delete pages, render markdown, nested tree, persist after reload.

Suggested 5 tasks:
1. W6-1: Knowledge base backend model + API (vex_agent)
2. W6-2: Wiki page tree UI (zen_agent)
3. W6-3: Markdown editor + viewer wired to API (vex_agent)
4. W6-4: Wiki search / recent pages (vex_agent or zen_agent)
5. W6-5: Knowledge base QA gate (zen_agent)

---

## 11. Key files and docs

| File | Purpose |
|---|---|
| `AGENTS.md` | Zero native design rule + agent instructions |
| `DECISIONS.md` | Design decisions (D1-D8) |
| `PROJECT-STATUS.md` | Current status + follow-ups |
| `.hermes/plans/2026-08-25_111817-stw-master-plan-L1.md` | L1 master plan |
| `app/w5-qa-report.md` | Latest QA evidence |
| `backend/models.py` | SQLAlchemy models |
| `backend/app.py` | FastAPI routes |

---

## 12. Environment gotchas

- Backend venv: `backend/.venv/Scripts/python.exe`
- `email-validator` rejects reserved TLDs like `@test.local`. Use `@example.com` in tests.
- bcrypt is used directly (passlib removed due to incompatibility with bcrypt>=4.1).
- Docker Desktop on this PC occasionally kills its Linux engine mid-build. Restart Docker Desktop if build fails with `rpc error ... EOF`.

---

*Written by Vex for the next fresh session. Update this file whenever a new wave completes or major project facts change.*
