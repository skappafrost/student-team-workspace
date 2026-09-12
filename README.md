# Student Team Workspace (STW)
[![CI](https://github.com/skappafrost/student-team-workspace/actions/workflows/ci.yml/badge.svg)](https://github.com/skappafrost/student-team-workspace/actions/workflows/ci.yml)

A team collaboration dashboard for student teams — kanban boards, chat, wiki, files, calendar, and notifications in one place.

Built by a student team with AI agent assistance (Hermes Agent multi-agent kanban workflow).

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query/Table/Form, dnd-kit, Recharts |
| Backend | FastAPI (Python), SQLAlchemy, Alembic migrations, JWT auth (access + refresh), bcrypt |
| Database | PostgreSQL (Docker) |
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
uvicorn app:app --reload --port 8000
```

### 2. Frontend (Next.js)

```bash
cd app
bun install                 # or npm install
cp env.example.txt .env.local
bun run dev                 # http://localhost:3000
```

> **Note (Windows):** if `bun run dev` crashes compiling `globals.css` (Turbopack), use `bun run dev:webpack` instead.

### 3. Default URLs

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/docs (Swagger)

## Features

- [x] Auth: register / sign-in / sign-out, JWT access + refresh tokens, httpOnly cookies
- [x] Workspaces: create, invite members, roles (owner/admin/member), settings
- [x] Kanban: multiple boards, drag & drop tasks (dnd-kit), task detail, quick add
- [x] Projects: create/link to boards
- [x] Chat: channels, real-time-ish messaging, channel management
- [x] Wiki: nested pages, tree sidebar, page viewer
- [x] Files: upload, list, download
- [x] Calendar: events CRUD, month view
- [x] Notifications: list, mark read, mark all read
- [x] Dark mode (default) + multiple themes

## Testing

```bash
# Backend
cd backend && python -m pytest --ignore=test_workspace_api.py --ignore=test_invites_api.py

# Frontend E2E (requires backend + frontend running)
cd app && node e2e-auth-flow.mjs
```

## Roadmap

- [ ] UI reskin: from SaaS template shell to a proper team-work dashboard (design sourced from online references per project rules)
- [ ] Real-time updates via WebSocket for chat + notifications
- [ ] AI assist features (search, summarize)
- [ ] Cloud deploy: Vercel (frontend) + Neon/Supabase (Postgres) + Render/Fly (FastAPI)

## License

MIT
