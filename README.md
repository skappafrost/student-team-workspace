# Student Team Workspace (STW)
[![CI](https://github.com/skappafrost/student-team-workspace/actions/workflows/ci.yml/badge.svg)](https://github.com/skappafrost/student-team-workspace/actions/workflows/ci.yml)

A team collaboration dashboard for student teams — kanban boards, chat, wiki, files, calendar, and notifications in one place.

Built by a student team with AI agent assistance (Hermes Agent multi-agent kanban workflow).

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query/Table/Form, dnd-kit, Recharts |
| Backend | FastAPI (Python), SQLAlchemy, Alembic migrations, JWT auth (access + refresh), bcrypt |
| Database | SQLite (local default) · PostgreSQL 16 (Docker Compose) |
| Dev tooling | Bun, Playwright (E2E), pytest, Docker Compose |

## Monorepo Layout

```
app/       # Next.js frontend
backend/   # FastAPI backend + Alembic migrations + Docker Compose
```

## Quick Start

### 1. Backend (FastAPI + Postgres via Docker)

```bash
cd backend
cp .env.example .env        # then edit values
docker compose up -d        # postgres + api
```

Or run without Docker:

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Frontend (Next.js)

```bash
cd app
bun install --frozen-lockfile   # or npm install
cp env.example.txt .env.local   # then add NEXT_PUBLIC_API_URL (see Environment variables)
bun run dev:webpack             # http://localhost:3000 (--webpack is mandatory, see note)
```

> **Note:** Turbopack is broken on this PC (`bun run dev` crashes compiling `globals.css`) — always use `bun run dev:webpack`.

### 3. Default URLs

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/docs (Swagger)

## Environment variables

### Backend (`backend/.env`, copied from `backend/.env.example`)

`docker compose config` / `up` fail without this file — copy it first.

| Variable | Example / default | Notes |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` | `stw_user` / `stw_password` / `stw_db` / `5432` | `postgres` service (Compose only) |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `postgres` / `5432` / `stw_user` / `stw_password` / `stw_db` | `backend` service DB connection |
| `DATABASE_URL` | unset (Compose builds `postgresql://…@postgres:5432/…`) | Local non-Docker default is SQLite (`sqlite:///./stw.db`) |
| `BACKEND_PORT` | `8000` | Host port for `stw-backend` |
| `JWT_SECRET_KEY` | `super-secret-change-me-in-production` | Change this in production |
| `COOKIE_SECURE` | `false` | Must stay `false` for local HTTP dev |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated; REST middleware currently allows `*` |

### Frontend (`app/.env.local`, copied from `app/env.example.txt`)

| Variable | Value | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | **Not** in the example file — add it manually. Use `localhost`, not `127.0.0.1`, or chat realtime breaks (see Known limitations) |
| `NEXT_PUBLIC_SENTRY_*` / `SENTRY_AUTH_TOKEN` | see `env.example.txt` | Optional error tracking |

## LAN development (phone / teammate on Tailscale / Radmin / LAN)

```bash
# Backend — bind all interfaces (default 127.0.0.1 is localhost-only)
cd backend
.venv/Scripts/python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# Frontend — `next dev` already binds 0.0.0.0:3000, no extra flag needed
cd app
bun run dev:webpack
```

1. In `app/.env.local`, point the API at this PC's LAN address and restart the dev server:
   `NEXT_PUBLIC_API_URL=http://<this-pc-ip>:8000`
2. On the other device, open `http://<this-pc-ip>:3000`.
3. Use the **same host** for both URLs — chat WebSocket auth is cookie-based and cookies are host-scoped (ports are ignored), so `http://<ip>:3000` + `http://<ip>:8000` keeps realtime working.

Verified addresses on this PC (2026-09-12): Tailscale `100.101.29.11`, Radmin VPN `26.237.25.80`.

## Known limitations

- **No token revocation yet** — `POST /auth/logout` only clears the session cookie; already-issued JWTs stay valid until expiry (access 1 week, refresh 30 days, hardcoded).
- **In-memory WebSocket rooms (single worker only)** — channel rooms live in the uvicorn process; run exactly one worker, no multi-worker broadcast fan-out.
- **Turbopack is broken on this PC** — always `dev:webpack`; a full prod `next build` is heavy here, so prefer the dev server locally (Vercel for hosting).
- **WebSocket cookie-domain rule** — the browser opens the WS directly against `NEXT_PUBLIC_API_URL` with the `session_token` cookie, so that host must equal the page host: `http://localhost:8000` for local dev (`127.0.0.1` serves REST fine but realtime silently never connects).

## Features

- [x] Auth: register / sign-in / sign-out, JWT access + refresh tokens in an httpOnly session cookie, `GET /auth/me` (no standalone `/auth/refresh` rotation route yet)
- [x] Workspaces: create, invite members, roles (owner/admin/member), settings
- [x] Kanban: multiple boards, drag & drop tasks (dnd-kit), task detail, quick add
- [x] Projects: create/link to boards
- [x] Chat: channels + channel management, messages, WebSocket broadcast (`/ws/channels/{id}`)
- [x] Wiki: nested pages, tree sidebar, page viewer
- [x] Files: upload, list, download
- [x] Calendar: events CRUD, month view
- [x] Notifications: list, mark read, mark all read
- [x] Dark mode (default) + multiple themes

## Testing

```bash
# Backend (full suite: 300 tests)
cd backend
.venv/Scripts/python.exe -m pytest -q        # Windows
# source .venv/bin/activate && python -m pytest -q  # Linux/macOS

# Migrations — exactly 1 head expected
.venv/Scripts/python.exe -m alembic heads

# Frontend
cd app && bun run typecheck
```

# Frontend E2E (requires backend + frontend running)
cd app && node e2e-auth-flow.mjs
```

## Roadmap

- [ ] UI reskin: from SaaS template shell to a proper team-work dashboard (design sourced from online references per project rules)
- [ ] Real-time updates via WebSocket for chat + notifications
- [ ] AI assist features (search, summarize)
- [ ] Cloud deploy: Vercel (frontend) + Neon/Supabase (Postgres) + Render/Fly (FastAPI)

## Dev shortcuts (Makefile)

```bash
make dev   # Postgres (Docker) + backend uvicorn :8000 + frontend :3000 (webpack)
make test  # backend pytest + frontend typecheck
make seed  # placeholder until T045 manage.py lands
```

Requires Docker (for Postgres), `backend/.venv`, and `bun install` in `app/`.

## License

MIT
