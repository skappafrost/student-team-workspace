# Contributing

## Setup

1. Backend: `cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt`
2. Apply migrations: `./.venv/Scripts/python -c "import os; os.environ['DATABASE_URL']='sqlite:///./stw.db'; from alembic.config import Config; from alembic import command; command.upgrade(Config('alembic.ini'), 'head')"` (from `backend/`)
3. Frontend: `cd app && bun install && cp env.example.txt .env.local && bun run dev`

## Workflow

1. Branch from `main`: `git checkout -b <feature-slug>` (or the active backlog branch)
2. Make changes; keep them surgical — only what the task needs
3. Run checks (below) — all must pass before committing
4. Open a PR against `main`; never merge your own PR — a teammate reviews

## Checks

```bash
# Backend tests (201 tests)
cd backend && ./.venv/Scripts/python -m pytest -q

# Backend lint
cd backend && ./.venv/Scripts/python -m ruff check .

# Frontend typecheck
cd app && bunx tsc --noEmit

# Frontend lint (oxlint, not eslint)
cd app && bun run lint

# Frontend build
cd app && bun run build

# Dependency audit
cd app && bun audit --prod
cd backend && ./.venv/Scripts/python -m pip_audit
```

## Conventions

### Backend (`backend/`)

- FastAPI routers in `routers/`, SQLAlchemy 2.0 typed models in `models.py`, Pydantic schemas in `schemas.py`
- Migrations: `alembic revision --autogenerate -m "<name>"`, then review the generated file
- RBAC: `require_permission("<domain>.<action>")` dependency; add new permissions to the map in `authorization.py`
- Cross-cutting side effects (notifications, activity feed) go through `services.py` (`notify`, `log_activity`)
- Tests: `test_<area>.py`, TestClient with `X-Test-User-Id` / `X-Test-User-Role` headers

### Frontend (`app/`)

- API layer per feature: `api/types.ts` → `api/service.ts` → `api/queries.ts`; all HTTP goes through `createApiClient` from `src/lib/api-client.ts` — never raw `fetch` for JSON APIs
- Data fetching: React Query (`useSuspenseQuery` / `useMutation`), key factories (`entityKeys.list/detail`)
- BFF: Next.js route handlers in `src/app/api/` proxy to the backend, attaching the session cookie; resolve the workspace server-side
- UI: shadcn/ui on Base UI (not Radix) — use `render={<Button/>}` instead of `asChild`; icons only from `@/components/icons`
- Page headers: `PageContainer` props (`pageTitle`, `pageDescription`); never a raw `<Heading>`
- Forms: `useAppForm` from `@/lib/form` + field components in `@/components/forms/fields`
- Style: single quotes, no trailing comma, 2-space indent (oxfmt enforced)

## Commit style

`type(scope): summary` — e.g. `feat(S07): admin audit log endpoint`. Reference the backlog task id when applicable.

## Security notes

- Never commit secrets; `.env.local` stays local
- Keep dependencies vetted: run both audits before adding a package; `bunfig.toml` enforces a 7-day minimum release age
