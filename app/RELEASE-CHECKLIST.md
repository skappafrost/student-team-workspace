# STW Release Checklist — W0–W10

> **Scope:** Local-first release. Cloud deployment is intentionally out of scope for this wave.
> **Updated:** 2026-09-03 (W10-3)

---

## 1. Wave status

| Wave | Theme | Status | Key deliverables |
|------|-------|--------|------------------|
| W0 | Design decisions & tooling | ✅ Done | `design-references/catalogs/DECISIONS.md` locked (8 decisions, 51/51 reference ids verified) |
| W1 | App shell & theme | ✅ Done | Dark default theme, SSR mode cookie, Linear-style sidebar with 7 nav sections, motion D6 spec |
| W2 | Auth, workspace, route guard | ✅ Done | JWT client, sign-in/up, workspace settings, proxy guard, e2e pass |
| W3 | Projects + Kanban | ✅ Done | Projects CRUD wired to backend, kanban dnd + optimistic UI + task detail |
| W4 | Calendar + kanban polish | ✅ Done | Calendar page, task detail panel, kanban cookie-domain fix |
| W5 | Chat + realtime | ✅ Done | Channels/messages API, chat UI page, WebSocket broadcast, chat QA gate |
| W6 | Knowledge base | ✅ Done | Wiki page tree, markdown editor/viewer wired to API, search + recent pages |
| W7 | Files + notifications | ✅ Done | File upload/list, notifications list + mark read, proxy API |
| W8 | AI layer | ✅ Done | AI summary + search UI wired to backend |
| W9 | Chat polish | ✅ Done | Author display name on messages, create-channel dialog + empty-state CTAs |
| W10 | QA fixes + docs | 🔄 In progress | W10-3 local run docs + release checklist |

---

## 2. Known issues

| # | Issue | Impact | Workaround / Owner |
|---|-------|--------|--------------------|
| 1 | **WS dev cookie-domain footgun** | WebSocket auth fails if `NEXT_PUBLIC_API_URL` uses an IP address instead of `localhost`. | Always set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `.env.local`. |
| 2 | **Message author fallback** | Some chat messages may still fall back to raw `author_id` if display name lookup misses. | Refresh the page; backend now returns `display_name`. Fixed in W9-1. |
| 3 | **No-workspace CTA** | Empty-state CTAs exist but may not guide new users to create a workspace in every entry point. | Use `/dashboard/settings?tab=workspace` to create a workspace manually. |

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
   - `backend/README.md` for local backend setup.
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

1. Identify the correct repo folder (for this project: `Team-workspace/app/`).
2. Back up or remove the stray `.git` directory.
3. Set the default workdir for the board:

```bash
hermes kanban boards set-default-workdir stw "C:/Users/Ha Trung/Documents/Team-workspace/app"
```

4. Reclaim and re-dispatch affected tasks.

### Verify a completed task

Required evidence per task type:

| Type | Evidence |
|------|----------|
| Backend | `pytest` pass count, migration head applied, `/health` 200 |
| Frontend UI | Screenshot, typecheck/build pass, E2E pass |
| Integration | End-to-end test result JSON, register/login flow works |
| Docs | Commit hash, file path, no secrets |

---

## 5. Local run verification (W10-3 acceptance)

- [ ] Backend virtualenv created, dependencies installed, `.env` configured.
- [ ] `alembic upgrade head` runs without error.
- [ ] `uvicorn app:app --host 127.0.0.1 --port 8000 --reload` starts and `/health` returns 200.
- [ ] Frontend `.env.local` contains `NEXT_PUBLIC_API_URL=http://localhost:8000`.
- [ ] `bun run dev` starts the app at http://localhost:3000.
- [ ] Register and login flows complete successfully.
- [ ] `bun run typecheck` and `bun run build` pass.
- [ ] No secrets committed in docs or `.env` files.
