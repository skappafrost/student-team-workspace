# STW Release Checklist

> **Scope:** Local-first release. Cloud deployment is intentionally out of scope for now.
> **Updated:** 2026-09-19
> **Verified on:** `pytest -q` **770 collected / 769 passed** (SQLite) · `bun run typecheck` clean · `alembic heads` = 1 (`prs01_presence_state`) · `ruff check .` from `backend/` clean. Re-run these before quoting the line — every number in this repo's docs went stale once already by staying literal.

---

## 1. Wave status

| Wave | Theme | Status | Key deliverables |
|------|-------|--------|------------------|
| W0 | Design decisions & tooling | ✅ Done | `design-references/catalogs/DECISIONS.md` locked (outside this repo, in `Team-workspace/`) |
| W1 | App shell & theme | ✅ Done | Dark default theme, SSR mode cookie, Linear-style sidebar with 7 nav sections, motion D6 spec |
| W2 | Auth, workspace, route guard | ✅ Done | JWT client, sign-in/up, workspace settings, proxy guard, `app/tests/middleware.auth.spec.ts` (runs in CI job `frontend-e2e`) |
| W3 | Projects + Kanban | ✅ Done | Projects CRUD wired to backend, kanban dnd + optimistic UI + task detail |
| W4 | Calendar + kanban polish | ✅ Done | Calendar page, task detail panel, kanban cookie-domain fix |
| W5 | Chat + realtime | ✅ Done | Channels/messages API, chat UI page, WebSocket broadcast, chat QA gate |
| W6 | Knowledge base | ✅ Done | Wiki page tree, markdown editor/viewer wired to API, search + recent pages |
| W7 | Files + notifications | ✅ Done | File upload/list, notifications list + mark read, proxy API |
| W8 | AI layer | ✅ Done | AI summary + search UI wired to backend |
| W9 | Chat polish | ✅ Done | Author display name on messages, create-channel dialog + empty-state CTAs |
| W10 | QA fixes + docs | ✅ Done | Local run docs + this checklist |
| T-wave | Security audit fixes (T001–T050) | ✅ Merged | T003 test-auth gate, T004 real-JWT fixtures, T009 bcrypt policy, T015 duplicate-membership guard, T040 file-delete + orphan sweeper — all landed (#1–#11) |
| TA-wave | Backend contract hardening | ✅ Merged | Auth refresh + secret governance, upload ingress/egress + quota, pagination contract, notification fan-out, WS auth, N+1 + indexes, dialect parity, ops maintenance, observability, coverage floor, security regression pack (#123–#175) |
| Recovery | Repairs after squash-merges dropped wiring | ✅ Merged | Restored backend import, `/auth/refresh`, upload path, message-search escaping; narrowed the `conftest.py` exception mask that had been hiding the breakage; merged the split Alembic heads (#185, #188) |
| S-wave | Realtime presence | 🔄 In progress | S3 single-head + S4 `PresenceState` (#188), S5 presence service + HTTP set/list + WS fan-out (#189). **S6 presence UI (frontend) not started** |

---

## 2. Known issues

| # | Issue | Impact | Workaround / Owner |
|---|-------|--------|--------------------|
| 1 | **WS dev cookie-domain footgun** | WebSocket auth fails if `NEXT_PUBLIC_API_URL` uses an IP/`127.0.0.1` instead of the page host. The browser opens the WS directly against that URL with the `session_token` cookie, and cookies are host-scoped (`SameSite=Lax`). This breaks **every** socket the same way — chat and presence both `4401` before `accept()`. `app/.env.local` on the current dev machine has `127.0.0.1`, so realtime is broken right now locally. It cannot come from a clone — the file is gitignored and `app/env.example.txt` does not define the variable at all (README says add it by hand), which is precisely why the mistake recurs. | Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `app/.env.local` for local dev (same host for LAN: `http://<ip>:8000`). |
| 2 | ~~No token revocation~~ **fixed** | Sessions are revocable: each login writes an `auth_sessions` row keyed by the JWT `jti`, and `POST /auth/logout` / `/auth/logout-all` revoke it, so a logged-out token gets `401` everywhere — including WS handshakes (`4401` before `accept()`). Refresh tokens rotate single-use and a replay revokes the whole family. | Residual gap: revocation is checked per **request**, not mid-connection — a socket opened before logout stays open until it closes. |
| 3 | **In-process realtime state** | Channel rooms, the per-user notification room, the presence socket refcount and the WS ticket store all live in the uvicorn process. | Never run multiple uvicorn workers (the Dockerfile and Makefile don't). Scale-out needs a shared store, not more sockets. |
| 4 | **Turbopack broken on this PC** | `bun run dev` crashes compiling `globals.css`. | Always `bun run dev:webpack`. |

---

## 3. How to seed the next wave

1. Review the current board: `hermes kanban board stw`.
2. Create a new wave card (e.g., `W11`) with the planned theme.
3. Decompose into child cards:
   - One design task for `zen_agent` (UI/UX, motion).
   - One backend task for `vex_agent` (API, models, migrations).
   - One integration/QA task for `vex_agent` or `zen_agent` (wire + verify).
4. Set dependencies with `parents=[...]` so design/integration waits on backend when needed.
5. Add acceptance criteria referencing:
   - `stw/backend/README.md` for local backend setup.
   - This checklist for known issues to avoid regressions.
   - `AGENTS.md` / `CLAUDE.md` for code conventions.
6. Include verification evidence: commit hash, typecheck/build pass, and (for UI) screenshot or E2E result.

---

## 4. Kanban recovery recipes

### Reclaim a stuck task

A task may become stuck in `running` if the worker process crashes or the session is interrupted.

```bash
# List running tasks
hermes kanban board stw

# Reclaim a specific task (marks it ready again)
hermes kanban reclaim stw <task-id>
```

### Dispatch a reclaimed task

```bash
# Dispatch up to N ready tasks of a profile
hermes kanban dispatch stw --profile zen_agent --max 2
hermes kanban dispatch stw --profile vex_agent --max 2
```

### Recover from a stray `.git` in the workspace root

If a worktree task ever spawns in the wrong folder and leaves a stray `.git`:

1. Identify the correct repo folder (for this project: `C:/Users/Ha Trung/Documents/Team-workspace/stw`).
2. Back up or remove the stray `.git` directory.
3. Set the default workdir for the board:

```bash
hermes kanban boards set-default-workdir stw "C:/Users/Ha Trung/Documents/Team-workspace/stw"
```

4. Reclaim and re-dispatch affected tasks.

### Verify a completed task

Required evidence per task type:

| Type | Evidence |
|------|----------|
| Backend | `pytest` pass count, migration head applied, `/health` 200 |
| Frontend UI | Screenshot, `bunx oxlint --deny-warnings src` + typecheck + build pass, `bunx playwright test` pass |
| Integration | End-to-end test result JSON, register/login flow works |
| Docs | Commit hash, file path, no secrets |

---

## 5. Local run verification

- [ ] Backend virtualenv created, dependencies installed, `backend/.env` copied from `.env.example` (Compose **fails** without it — `docker compose config` exits 1).
- [ ] `alembic upgrade head` runs without error; `alembic heads` shows exactly 1 head.
- [ ] `.venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload` starts and `/health` returns 200. (`--host` is the **bind** address; `NEXT_PUBLIC_API_URL` must still name the *page's* hostname — see §1.)
- [ ] Frontend `app/.env.local` contains `NEXT_PUBLIC_API_URL=http://localhost:8000` (plus Sentry vars from `env.example.txt`, optional).
- [ ] `bun run dev:webpack` starts the app at http://localhost:3000 (`--webpack` is mandatory — Turbopack is broken on this PC).
- [ ] `make realtime` passes: it starts both servers itself and asserts a message sent by one browser renders in a second browser's channel. A `/ws/...` line in the uvicorn log is **not** this proof — `[accepted]` only means the application accepted.
- [ ] Register and login flows complete successfully (`cd app && node e2e-auth-flow.mjs`).
- [ ] `bun run typecheck`, `bunx oxlint --deny-warnings src` and `bun run build` pass; backend `python -m pytest -q` fully green (re-run, don't quote a stored count); `bunx playwright test` green.
- [ ] No secrets committed in docs or `.env` files.
