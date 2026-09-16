# Contributing

## Setup

1. Backend: `cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt` (Windows; on Linux/macOS use `.venv/bin/pip`)
2. Apply migrations: `./.venv/Scripts/python -m alembic upgrade head` (from `backend/`; Linux/macOS: `.venv/bin/python`)
3. Frontend: `cd app && bun install --frozen-lockfile && cp env.example.txt .env.local` — then add `NEXT_PUBLIC_API_URL=http://localhost:8000` to `.env.local` (it is not in the example file; use `localhost`, not `127.0.0.1`, or chat realtime breaks)

Default dev URLs: frontend `http://localhost:3000`, backend `http://localhost:8000` (Swagger at `/docs`).

## Branch + PR flow (how we actually work)

1. Branch from latest `main`:
   - `git checkout -b feat/<slug>` for product features
   - `git checkout -b harden/<slug>` for audit/hardening work
2. Rebase on `origin/main` right before pushing — the `harden/*` lane lands continuously, so `main` moves often. Rebase again if CI shows conflicts.
3. Keep a PR to one logical change; diff should be roughly ≤ 400 changed lines. Split if bigger.
4. Push and open a **draft** PR against `main`.
5. The PR body must contain the **validation transcript**: the commands you ran plus their output summary (pytest pass count, CI job results, `alembic heads` count). No transcript, no review.
6. Mark the PR ready for review once CI is green.
7. **Never merge your own PR.** A teammate (reviewer) reviews and squash-merges. No direct pushes to `main`.

Merging is squash-merge only; the commit message keeps the PR title.

## Checks

```bash
# Backend tests (Windows; .venv/bin/python on Linux/macOS)
cd backend && ./.venv/Scripts/python -m pytest -q

# Backend lint
cd backend && ./.venv/Scripts/python -m ruff check .

# Migrations — exactly 1 head expected
cd backend && ./.venv/Scripts/python -m alembic heads

# Frontend typecheck
cd app && bunx tsc --noEmit

# Frontend lint (oxlint, not eslint)
cd app && bun run lint

# Frontend build (webpack — see Known limitations)
cd app && bun run build

# Dependency audit
cd app && bun audit --prod
cd backend && ./.venv/Scripts/python -m pip_audit
```

CI (`.github/workflows/ci.yml`) runs four jobs on every push and PR: `backend` (pytest on SQLite), `backend-pg` (pytest on Postgres 16), `frontend` (typecheck), `demo-pack` (validates `scripts/demo-packs/busy-workspace.json` structure). All four must be green before a PR is marked ready.

### SQLite + PostgreSQL parity

CI runs the full pytest suite twice — once against SQLite (`backend` job) and once against Postgres (`backend-pg` job). Both must stay green. Never write SQLite-only behavior, and never assume a dialect: a migration that renders valid DDL on one engine can be invalid on the other (e.g. a boolean `server_default` must be `sa.false()`/`"false"`, not `sa.text("0")` — Postgres rejects an unquoted integer default on a boolean column). The `backend-pg` job is the safety net that catches it; local SQLite-only pytest does not.

## Conventions

### Backend (`backend/`)

- FastAPI routers live in `routers/` (one file per domain: `auth`, `workspaces`, `invites`, `members`, `channels`, `messages`, `projects`, `tasks`, `events`, `pages`, `files`, `notifications`, `ai`, `account`). Do not reorganize this layout — extend it.
- Shared plumbing: `dependencies.py` (auth, token minting, resource getters), `authorization.py` (Role + RBAC checks), `channel_access.py` (channel membership helpers). Cross-cutting side effects (notifications, activity feed) go through `services.py` (`notify`, `log_activity`).
- SQLAlchemy 2.0 typed models in `models.py`, Pydantic schemas in `schemas.py`, env-driven config in `config.py`.
- Rate limiting: per-route dependencies in `rate_limit.py` (`login_limit`, `register_limit`, `upload_limit`, `ai_limit`) plus a fallback sliding-window cap for uncovered write routes. Returns `429` with a `Retry-After` header.
- Tests: `test_<area>.py`. Use the real-JWT fixtures from `conftest.py` — `make_user(db, ...)` to create an identity and `as_user(client, user_id)` / `auth_headers(user_id)` to authenticate. The legacy `X-Test-User-Id` / `X-Test-User-Role` bypass headers are gated to test/dev environments only and must not be used by new tests.
- Migrations: `alembic revision --autogenerate -m "<name>"`, then review the generated file. **Exactly one head** — never add a migration with `down_revision=None` when another head exists; rebase/merge heads instead.
- RBAC: `require_permission("<domain>.<action>")` dependency; the permission→role map lives in `authorization.py`.

### Frontend (`app/`)

- API layer per feature: `api/types.ts` → `api/service.ts` → `api/queries.ts`; all HTTP goes through `createApiClient` from `src/lib/api-client.ts` — never raw `fetch` for JSON APIs
- Data fetching: React Query (`useSuspenseQuery` / `useMutation`), key factories (`entityKeys.list/detail`)
- BFF: Next.js route handlers in `src/app/api/` proxy to the backend, attaching the session cookie; the current workspace is resolved server-side as the first entry of `GET /workspaces`
- UI: shadcn/ui on Base UI (not Radix) — use `render={<Button/>}` instead of `asChild`; icons only from `@/components/icons`
- Page headers: `PageContainer` props (`pageTitle`, `pageDescription`); never a raw `<Heading>`
- Forms: `useAppForm` from `@/lib/form` + field components in `@/components/forms/fields`
- Style: single quotes, no trailing comma, 2-space indent (oxfmt enforced)

### Design rule

Zero native design: every UI element, effect, and animation must be traceable to an online reference (library, CDN, or `design-references/`). See `PROJECT-STATUS.md` §2.

## Commit style

`type(scope): summary` — e.g. `feat(S07): admin audit log endpoint`. Reference the backlog task id when applicable.

## Ops tools

Run from `backend/` (the `.venv` interpreter on Windows):

- `python manage.py seed-demo` — idempotent demo dataset (users, projects, tasks, channels, messages, pages)
- `python manage.py create-user --email … --password …` / `reset-password` / `db-status` — user + migration sanity commands
- `python -m maintenance purge-orphans` — dry-run report of orphaned uploads; add `--apply` to repair (refuses to touch Postgres without `--apply`)

## Security notes

- Never commit secrets; `.env`/`.env.local` stay local (and `.gitignore`d)
- The backend refuses to start with the default `JWT_SECRET_KEY` outside dev/test environments — set a real secret in production
- Keep dependencies vetted: run both audits before adding a package; `bunfig.toml` enforces a 7-day minimum release age
