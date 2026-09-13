# Student Team Workspace — Frontend (`app/`)

Next.js 16 (App Router) + TypeScript + Tailwind CSS v4 + shadcn/ui frontend for the
Student Team Workspace (STW) monorepo. It pairs with the FastAPI backend in `../backend`
(see `backend/README.md` for the backend side).

> Origin note: the UI shell started from the Kiranism `next-shadcn-dashboard-starter`
> template. The template's demo content (products / users / billing, SaaS marketing copy)
> has been replaced by the real STW features listed below. If you ever spot leftover
> products/users/billing text in the app, treat it as stale and fix it — do not build on it.

## Features (wired to the backend, not mockups)

| Page           | Route                          | What it does                                              |
| :------------- | :----------------------------- | :-------------------------------------------------------- |
| Overview       | `/dashboard/overview`          | Cards + charts dashboard (parallel routes per section)    |
| Projects       | `/dashboard/projects`          | Project list and project workspace                        |
| Kanban         | `/dashboard/kanban`            | Drag-and-drop task board (columns, priorities, assignees) |
| Chat           | `/dashboard/chat`              | Channels, messages, composer                              |
| Wiki           | `/dashboard/wiki`              | Team wiki pages                                           |
| Files          | `/dashboard/files`             | Team file uploads / downloads                             |
| Calendar       | `/dashboard/calendar`          | Team events                                               |
| Notifications  | `/dashboard/notifications`     | Notification center, mark-as-read / mark-all-as-read      |
| AI chat        | `/dashboard/ai-chat`           | AI search / summarize / chat panels                       |
| Settings       | `/dashboard/settings`          | Workspace settings                                        |
| Sign in/up     | `/auth/sign-in`, `/auth/sign-up` | Email + password auth                                   |

Auth uses a login/register proxy plus an `httpOnly` `session_token` cookie (see
[BFF pattern](#bff-pattern-route-handlers-proxy-the-backend) below).

## Getting started

Prerequisites: [Bun](https://bun.sh) installed, and the backend running
(see `backend/README.md` — it serves `http://localhost:8000` by default).

```bash
cd app

# 1. Install dependencies (exact lockfile versions)
bun install --frozen-lockfile

# 2. Copy the example env file and point it at the backend
cp env.example.txt .env.local
```

Then add the backend URL to `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

> [!IMPORTANT]
> Use `http://localhost:8000` (not an IP address). The dev server must be on the same
> `localhost` origin so the backend's `session_token` cookie is sent correctly.

```bash
# 3. Start the dev server (webpack mode — see note below)
bun run dev:webpack
```

The app runs at http://localhost:3000.

> [!WARNING]
> `bun run dev` (Turbopack) is broken on this machine — it crashes compiling
> `globals.css`. Always use `bun run dev:webpack` here.

## Scripts

| Command                | What it does                                                        |
| :--------------------- | :------------------------------------------------------------------ |
| `bun run dev:webpack`  | Dev server in webpack mode (**use this one**)                       |
| `bun run dev`          | Dev server in Turbopack mode (broken on this machine, see warning)  |
| `bun run build`        | Production build                                                    |
| `bun run start`        | Serve a production build                                            |
| `bun run typecheck`    | `tsc --noEmit`                                                      |
| `bun run lint`         | OxLint                                                              |
| `bun run gen:api`      | Regenerate typed backend client (see below)                         |
| `bun run cleanup --list` | Template leftover: lists removable demo features; STW does not rely on it |

## BFF pattern: route handlers proxy the backend

The browser never talks to FastAPI directly. Every backend call goes through a
Next.js route handler in `src/app/api/*`, which forwards the `session_token` cookie:

- Client services (e.g. `src/features/chat/api/service.ts`) call same-origin endpoints:
  `fetch('/api/channels/...', { credentials: 'include' })`.
- Route handlers (e.g. `src/app/api/notifications/route.ts`) read the cookie via
  `cookies()` from `next/headers` and forward it as `Cookie: session_token=...` to
  `${NEXT_PUBLIC_API_URL}` (default `http://localhost:8000`), with `cache: 'no-store'`.
- Auth is proxied the same way: `src/app/api/auth/session/route.ts` forwards
  login/register to the backend's `/auth/{login,register}` and passes the backend's
  httpOnly `Set-Cookie` back to the browser.

When adding a feature, add both halves: a `src/app/api/<thing>/route.ts` proxy and a
`src/features/<thing>/api/service.ts` client that uses `credentials: 'include'`.

## API type generation

Backend response types are generated from the FastAPI OpenAPI schema — never
hand-maintained — via [`openapi-typescript`](https://openapi-typescript.dev):

```bash
bun run gen:api
```

This spins up the backend with `uvicorn` on `127.0.0.1:8123` using a throwaway temp
SQLite DB (never the dev `stw.db`, never Postgres), fetches `/openapi.json`, and emits
the typed client to `src/types/api.d.ts`. That file starts with a
`DO-NOT-EDIT-GENERATED` header — do not edit it by hand, regenerate instead.
To consume a type: `components['schemas']['<Name>']` from `@/types/api`.

Env overrides for the script: `STW_VENV_PYTHON` (Python with uvicorn+fastapi installed),
`GEN_API_PORT` (default `8123`). See `scripts/gen-api.mjs` header for details.

## Folder structure

```plaintext
src/
├── app/                           # Next.js App Router
│   ├── auth/sign-in|sign-up/       # Auth pages
│   ├── dashboard/                  # Authed area: overview, projects, kanban,
│   │                               # chat, wiki, files, calendar, notifications,
│   │                               # ai-chat, settings
│   └── api/                        # BFF proxies: auth, channels, events, files,
│                                   # notifications, pages, projects, tasks,
│                                   # workspace, ai/*
├── features/                      # Feature modules (ai, ai-chat, calendar, chat,
│                                  # files, kanban, notifications, overview,
│                                  # projects, wiki, workspace)
├── components/                    # Shared + shadcn/ui primitives, layout, kbar
├── lib/                           # api-client, auth, query-client, utils, ...
├── hooks/ | config/ | constants/  # Shared hooks, navigation/data-table config
└── types/                         # api.d.ts (GENERATED — see above)
```

`docs/` holds the inherited template guides (`deployment.md`, `forms.md`, `themes.md`);
they describe generic Next.js/shadcn patterns, not STW specifics.

## Verify

```bash
# Type check
bun run typecheck

# Production build
bun run build
```

Backend suite sanity (from the repo root, using the main checkout venv):

```bash
C:/Users/Ha\ Trung/Documents/Team-workspace/stw/backend/.venv/Scripts/python.exe -m pytest -q
```

Baseline on `main`: 319 passed.
