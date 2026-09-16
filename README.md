<div align="center">

# Student Team Workspace

**One workspace for student teams — chat, kanban, wiki, files, calendar and deadlines, connected by a shared activity graph.**

[![CI](https://github.com/skappafrost/student-team-workspace/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/skappafrost/student-team-workspace/actions/workflows/ci.yml)
[![Backend tests](https://img.shields.io/badge/backend%20pytest-408%20passing-brightgreen)](#testing)
[![Frontend](https://img.shields.io/badge/frontend-tsc%20%7C%20oxlint%20%7C%20playwright-brightgreen)](#testing)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

*Built by a student team, with AI agents as teammates — Hermes Agent multi-agent kanban + Claude Code pair-programming. Every visual is sourced, never native-designed (see [Zero Native Design Rule](#zero-native-design-rule)).*

</div>

---

## What it is

A local-first team workspace that keeps **context connected**: the message that mentions a task links to the task, the task links to its board, the board links to the files attached to its cards, and everything writes to one **activity graph** per workspace. Notifications and the deadlines page are *computed* from that graph, not maintained by hand.

```
                         ┌──────────────────────────────────────────────┐
                         │                   BROWSER                     │
                         │  Next.js 16 · React 19 · Tailwind v4 · shadcn │
                         │   App Router pages ──▶ BFF route handlers      │
                         └───────────────────────┬──────────────────────┘
                                                 │  httpOnly session cookie (server-side)
                                                 ▼
        ┌────────────────────────────────────────────────────────────────────┐
        │                              FASTAPI :8000                              │
        │                                                                          │
        │   auth ─┬─ workspaces ─┬─ channels ─┬─ messages ─┬─ files            │
        │   (JWT │  invites     │  DMs       │  reactions │  (quota)          │
        │  + jti │  members RBAC│  WS rooms  │  threads   │                  │
        │ revoke)│  activity    │            │  search    │                  │
        │         │  audit log  │            │            │                  │
        │   projects ─ tasks ─ pages/versions ─ events ─ notifications ─ AI  │
        │                                                                          │
        │   rate_limit · logging_mw · config · channel_access · authorization  │
        └───────────────┬──────────────────────────────────────┬───────────────┘
                        ▼                                      ▼
        ┌───────────────────────────────┐              ┌──────────────────────┐
        │   SQLite (local default)      │              │  /uploads (blobs)    │
        │   PostgreSQL 16 (CI + Compose)│              │  per-workspace quota  │
        └───────────────────────────────┘              └──────────────────────┘
```

*The browser never calls the API origin directly — every request goes through a BFF route handler, which is why auth is a single cookie and CORS stays quiet.*

## Feature matrix

```
 AUTH          register · sign-in · sign-out · sign-out-everywhere · session
               revocation (jti) · access + refresh tokens · account export
               & verified deletion (tombstone)            ✅ shipped

 WORKSPACES    create · invite (expiring tokens) · roles
               owner ▸ admin ▸ member ▸ guest · transfer ownership
               · workspace switcher · per-workspace audit log ✅ shipped

 CHAT          channels (public/private) · DMs · threads (parent_id)
               · reactions · typing indicators · message search
               · edit / delete · realtime broadcast         ✅ shipped

 KANBAN        boards per project · drag & drop (dnd-kit) · bulk actions
               · deep-linkable project filter                ✅ shipped

 WIKI          nested pages · tree sidebar · [[wikilinks]] + backlinks
               · page version history & restore              ✅ shipped

 FILES         upload / list / download / delete · resource-linked uploads
               (project / task / message) · share-to-chat · image preview
               · ingress hardening + storage quota        🔶 hardening in PRs

 CALENDAR      event CRUD · month view · recurrence (daily/weekly/monthly) ✅ shipped

 NOTIFICATIONS per-user feed · mark read / mark all read · click-to-navigate
               · unread badges                              ✅ shipped

 DEADLINES     cross-workspace "my tasks" with overdue/today/week buckets  ✅ shipped

 ACTIVITY      workspace activity feed · audit log (admin)                 ✅ shipped

 AI ASSIST     search + summarize (provider-pluggable; deterministic
               offline fallback, no LLM key required)     🔶 stub-ready
```

## Tech stack

| Layer | Stack |
|---|---|
| **Frontend** | Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS v4 · shadcn/ui (Base UI) · TanStack Query/Table/Form/Virtual · dnd-kit · Recharts · kbar · nuqs · motion · sonner |
| **Backend** | FastAPI · SQLAlchemy 2.0 · Alembic · pydantic-settings · JWT (jti-revocable) · bcrypt · WebSocket rooms · in-memory sliding-window rate limiter |
| **Database** | SQLite (local default) · PostgreSQL 16 (Docker Compose + CI) — both must pass CI |
| **Quality** | pytest (backend) · Vitest + Playwright (client) · oxlint/oxfmt · ruff · GitHub Actions |
| **Design** | 11 sourced themes · WCAG AA contrast gate · token-only color policy |

## Repository layout

```
stw/
├── app/                        # Next.js client
│   ├── src/
│   │   ├── app/                # routes + api/ BFF route handlers (26 groups)
│   │   ├── features/           # 14 feature folders (chat, kanban, wiki, …)
│   │   ├── components/ui/      # shadcn primitives + Empty / NotificationCard
│   │   ├── components/themes/  # theme selector, mode toggle, font config
│   │   ├── styles/themes/      # 11 theme token sheets (OKLCH)
│   │   └── lib/                # api-client, server-workspace, i18n, query-client
│   ├── tests/                  # Playwright e2e + capture suites
│   ├── scripts/                # theme contrast audit/fix/attribution
│   ├── design-references/      # Zero Native Design Rule catalog
│   └── qa-evidence/            # UI screenshots (policy-governed)
├── backend/                    # FastAPI + Alembic
│   ├── routers/                # 14 domain routers (57 endpoints)
│   ├── alembic/versions/       # single-head migration chain
│   ├── authorization.py        # Role hierarchy + permission checks
│   ├── channel_access.py       # private-channel predicate
│   ├── dependencies.py         # JWT sessions, current-user, resource getters
│   ├── ws.py                   # in-process room manager
│   ├── services.py             # notify() + log_activity() entry points
│   ├── rate_limit.py           # sliding-window limiter + middleware
│   └── test_*.py               # 32 test files · 408 tests
├── scripts/demo-packs/         # CI-validated demo data
├── docs/                       # API reference, contributing, release checklist
├── .github/workflows/ci.yml    # 4 jobs: backend · backend-pg · frontend · demo-pack
└── Makefile                    # dev · test · seed
```

## Quick start

```bash
# 1. Clone and enter
git clone https://github.com/skappafrost/student-team-workspace.git stw && cd stw

# 2. Backend — Postgres via Docker (recommended) or SQLite local
cd backend && cp .env.example .env && docker compose up -d
#    no Docker? → python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
#                 .venv/Scripts/python -m alembic upgrade head
#                 .venv/Scripts/python -m uvicorn app:app --port 8000 --reload

# 3. Frontend
cd ../app && bun install --frozen-lockfile
cp env.example.txt .env.local
echo 'NEXT_PUBLIC_API_URL=http://localhost:8000' >> .env.local   # ⚠️ localhost, not 127.0.0.1
bun run dev:webpack            # → http://localhost:3000
```

> **`dev:webpack` is mandatory on this PC** — Turbopack crashes compiling `globals.css` here. It is environment noise, not a code bug; do not "fix" it by deleting CSS.

**Dev URLs:** frontend `http://localhost:3000` · backend `http://localhost:8000/docs` (Swagger)

## Environment variables

**Backend** — `backend/.env` (copy from `backend/.env.example`; `docker compose` fails without it):

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` | `stw_user` / `stw_password` / `stw_db` / `5432` | Compose `postgres` service only |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `postgres` / `5432` / … | Compose `backend` service connection |
| `DATABASE_URL` | unset → SQLite `sqlite:///./stw.db` | Compose builds a `postgresql://…` URL instead |
| `BACKEND_PORT` | `8000` | Host port for `stw-backend` |
| `JWT_SECRET_KEY` | `super-secret-change-me-in-production` | **Startup refuses this default outside dev/test** — set a real key |
| `COOKIE_SECURE` | `false` | Keep `false` for local HTTP |
| `CORS_ORIGINS` | local defaults | Comma-separated; empty = localhost defaults |

**Frontend** — `app/.env.local` (copy from `app/env.example.txt`):

| Variable | Notes |
|---|---|
| `NEXT_PUBLIC_API_URL` | **Not in the example file — add manually.** Must be `localhost`, not `127.0.0.1`, or the chat WebSocket never connects (cookies are host-scoped) |
| `NEXT_PUBLIC_SENTRY_*` / `SENTRY_AUTH_TOKEN` | Optional error tracking |

## Testing

```bash
# Backend — 408 tests, runs identically on SQLite and PostgreSQL
cd backend && ./.venv/Scripts/python -m pytest -q

# Migrations — exactly one head expected
cd backend && ./.venv/Scripts/python -m alembic heads

# Frontend
cd app && bun run test          # Vitest (unit + component)
cd app && bun run typecheck     # tsc --noEmit
cd app && bun run lint          # oxlint
cd app && bun run audit:themes  # WCAG AA contrast gate (all 11 themes)
cd app && bun run test:e2e      # Playwright golden paths (needs :3000 + :8000)
cd app && bun run qa:evidence   # capture all surfaces, light + dark
```

CI enforces four jobs on every push and PR: `backend` (SQLite) · `backend-pg` (Postgres 16) · `frontend` (typecheck) · `demo-pack`. All four green before review.

> **SQLite/Postgres parity is mandatory.** A migration that renders valid DDL on one engine can be invalid on the other (a boolean `server_default` must be `sa.false()` / `"false"`, not `sa.text("0")` — Postgres rejects an unquoted integer default on a boolean column). The `backend-pg` job is the safety net; local SQLite-only pytest does not catch this.

## Project status

**v0.9 — platform complete, hardening lane in flight.** All core features shipped; the current sprint is a dedicated security/reliability pass (`harden/*` branch family) plus a client-experience program.

| Area | Status | Evidence |
|---|---|---|
| Feature surface | ✅ all core modules shipped | 57 endpoints · 19 models · 14 client features |
| Backend suite | ✅ 408 passing, 0 failing | `pytest -q` on SQLite + Postgres |
| Client tests | ✅ Vitest 8/8 · Playwright golden paths | `bun run test` / `test:e2e` |
| Alembic | ✅ single head | `alembic heads` |
| Type check | ✅ clean | `tsc --noEmit` |
| Contrast | ✅ WCAG AA on all 11 themes | `bun run audit:themes` |
| Realtime | 🔶 single-process rooms only | no cross-worker fan-out yet |
| Storage | 🔶 ingress + quota in review PRs | authenticated read path pending merge |
| AI assist | 🔶 provider-pluggable, offline fallback | no LLM wired yet |

**In flight (open PRs):** auth refresh + rotation (#123) · JWT secret governance (#124) · jti request session (#126) · upload ingress hardening (#128) · authenticated `/uploads` (#130) · storage quota (#132) · LIKE escape + enum docs (#134) · message→notification fan-out (#138) · pagination contract (#159) · WebSocket auth (#161) · docs rewrite (#160) · client-experience program (#137, changes requested).

## Roadmap

- [ ] **Realtime communication platform** — live presence, free audio/video calls, screen sharing, provider-agnostic signaling (`transport interface` boundary, no provider lock-in)
- [ ] **Storage provider abstraction** — swap local `/uploads` for S3-compatible or Google Drive via a provider interface
- [ ] **Cloud deploy** — Vercel (frontend) + Neon/Supabase (Postgres) + Render/Fly (FastAPI)
- [ ] **Real LLM provider** for AI search/summarize (interface already in place)
- [ ] **Search at scale** — replace `ilike` scans with an indexing abstraction

## How we work

**GitHub Flow, squash-merge only, no direct pushes to `main`.**

1. Branch from latest `main`: `feat/<slug>` (product) or `harden/<slug>` (audit/hardening). The hardening lane lands continuously, so `main` moves often — rebase right before pushing.
2. One PR = one logical change (~≤400 changed lines). Split if bigger.
3. The PR body **must** contain a validation transcript: the commands you ran plus their output summary (pytest pass count, CI results, `alembic heads` count). **No transcript, no review.**
4. **Never merge your own PR.** A teammate reviews and squash-merges.
5. SQLite and PostgreSQL must both pass; never write dialect-specific behavior.

Detailed: [`CONTRIBUTING.md`](CONTRIBUTING.md) · API reference: [`docs/API.md`](docs/API.md) · Status: [`PROJECT-STATUS.md`](PROJECT-STATUS.md)

## Zero Native Design Rule

**No agent designs UI from scratch — ever.** Every visual element (button, gradient, hover, micro-interaction, text treatment) must come from an external source: 21st.dev, Tailwind UI, shadcn registry, Framer Motion examples, CodePen, CDN libraries, design-system docs. Agents may only modify, adapt, or compose those assets.

Enforcement, not aspiration:

- `app/design-references/` — the catalog: one row per visual (source URL/id + adaptation note)
- `Source:` / `Design source:` attribution comment in every implementing file
- `bun run audit:themes` — WCAG AA 4.5:1 contrast gate across all 11 themes, light + dark
- Token-only colors (`var(--*)`); no hardcoded hex outside the allow-listed semantic accents
- Code review flags any visual without a reference entry — when in doubt, **remove the effect and use a sourced one**

The catalog ships with the client-experience program (PR #137, currently in review) — until it merges, reference entries live in that branch.

## Known limitations

- **Single-process realtime** — WS rooms live in the uvicorn process (`backend/ws.py`); run exactly one worker, no multi-worker fan-out yet.
- **Turbopack is broken on this PC** — always `bun run dev:webpack`; a full prod `next build` is heavy locally, so prefer the dev server (Vercel for hosting).
- **WebSocket cookie host rule** — the browser opens the WS against `NEXT_PUBLIC_API_URL` with the `session_token` cookie; that host must equal the page host (`localhost:3000` + `localhost:8000` works; `127.0.0.1` serves REST fine but realtime silently never connects).
- **AI assist runs its deterministic offline fallback** — no LLM provider is wired yet; the provider interface is in place.
- **Search is `ilike`-based** — fine at current scale, not indexed.

## Dev shortcuts

```bash
make dev    # Postgres (Docker) + backend uvicorn :8000 + frontend :3000 (webpack)
make test   # backend pytest + frontend typecheck
make seed   # demo data (until manage.py lands)
```

Requires Docker (for Postgres), `backend/.venv`, and `bun install` in `app/`.

## Team

Built by a student team with AI agents as teammates — Hermes Agent (multi-agent kanban workflow) and Claude Code (pair programming). PRs are authored by humans and agents alike; every PR is reviewed and squash-merged under the same rules.

## License

MIT — this project is MIT-licensed. (No `LICENSE` file is committed yet; add one
when redistributing.)
