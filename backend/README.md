# STW Backend

Student Team Workspace backend — FastAPI + SQLAlchemy + Alembic.

This README covers **local development only**. Cloud deployment is out of scope for this wave.

---

## Prerequisites

- Python 3.11+
- Windows: Git Bash / MSYS2 / WSL recommended for POSIX-style commands
- (Optional) `uv` or `venv` for virtual environment

---

## 1. Create and activate a virtual environment

```bash
# Using venv
python -m venv .venv

# Windows (Git Bash / MSYS2)
source .venv/Scripts/activate

# macOS / Linux
source .venv/bin/activate
```

---

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` includes FastAPI, Uvicorn, SQLAlchemy, Alembic, Pytest, and all runtime dependencies.

---

## 3. Configure environment variables

Copy the example file:

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

| Variable | Local value | Notes |
|----------|-------------|-------|
| `DATABASE_URL` | `sqlite:///./stw.db` | Default. SQLite is used for local development. |
| `JWT_SECRET_KEY` | any long random string | Used to sign JWT access/refresh tokens. |
| `COOKIE_SECURE` | `false` | Must be `false` for local HTTP dev. |
| `CORS_ORIGINS` | `http://localhost:3000` | Frontend origin. |
| `BACKEND_PORT` | `8000` | Uvicorn port. |

> [!WARNING]
> Never commit `.env` to version control. It is already ignored by `.gitignore`.
> Use a strong `JWT_SECRET_KEY` in production.

---

## 4. Run database migrations (Alembic)

With the virtual environment active and `DATABASE_URL` set:

```bash
# Check current migration state
alembic heads

# Apply all pending migrations
alembic upgrade head
```

**This is the schema source.** Every path that starts this backend migrates first: the README quickstart and `make dev` run `alembic upgrade head`, `backend/Dockerfile`'s `CMD` chains it before uvicorn, the Playwright backend `webServer` entry runs it in the same shell command that starts uvicorn, against `ci_e2e.db`, and `python smoke_server.py` applies it to `stw_smoke.db` in-process. Treat a successful `upgrade head` as what gives a fresh clone its schema — a database that was only ever `create_all`ed is the exception below.

`alembic` resolves the same database the app opens: `backend/alembic/env.py` reads `DATABASE_URL` from the process environment first and otherwise falls back to `config.Settings`, which is what reads `.env`. Copying `.env.example` to `.env` is enough for both; `alembic.ini`'s `sqlalchemy.url` is no longer consulted (it still holds the `driver://user:pass@localhost/dbname` template placeholder).

**One exception, and it bites quietly.** A database whose tables came from `Base.metadata.create_all` — the startup path `app.py` still runs (T036) and the one every test database uses — has no `alembic_version` row, so `alembic upgrade head` treats it as brand-new and dies on the first `CREATE TABLE` with "table already exists". That reads as a broken migration; it is an unstamped database.

### Repair recipe: an existing database `alembic upgrade head` refuses

```bash
cd backend
python manage.py db-status                    # tables present, "alembic version (applied): (none)"
python manage.py stamp                        # record `head` in `alembic_version`; no DDL, no data touched
alembic upgrade head                          # now a no-op, and later revisions apply normally
```

Stamping asserts a fact, so it refuses when the fact is false: an empty database gets `nothing to stamp: the database has no tables`, and you want `alembic upgrade head` there instead. Use `python manage.py stamp --db-url <url>` for a database other than `DATABASE_URL` — the flag is authoritative for this command, which matters because `alembic/env.py` reads `DATABASE_URL` from the process environment before anything else.

**Same repair for a Docker volume.** The data lives in the `postgres_data` volume, so the app has to stop writing while the stamp is recorded, and the repair runs against that volume's database rather than a SQLite file:

```bash
docker compose -f backend/docker-compose.yml stop backend      # app stops; postgres keeps running
cd backend
python manage.py stamp --db-url postgresql+psycopg2://stw_user:stw_password@localhost:5432/stw_db
docker compose -f backend/docker-compose.yml up -d             # start again; schema is now at head
```

`--db-url` is the URL from `backend/.env` / `docker-compose.yml` in the real deployment. Stamping does not upgrade data: if the volume is a release behind, run `alembic upgrade head` afterwards and let its migrations do the work.

---

## 5. Start the development server

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

The API will be available at:

- API root: http://127.0.0.1:8000
- OpenAPI docs: http://127.0.0.1:8000/docs
- "It is up" check: http://127.0.0.1:8000/readyz — 200 only when the database answers
  **and** `alembic_version` equals the single declared head; 503 with
  `{db: true, schema_current: false, alembic_applied: []}` means the chain never ran
  (that is the state to repair, see §4). This is the probe Playwright waits on.
- Liveness check: http://127.0.0.1:8000/health — cheap, touches no table, always 200.
  Use it to ask "is the process listening", never "can it serve".

---

## 6. Run tests

Most tests use an in-memory SQLite database and FastAPI's `TestClient`, so they do not require a running server.

Two tests require a live server on port `8000` and should be excluded from the default test run:

- `test_invites_api.py`
- `test_workspace_api.py`

Run the safe test suite with:

```bash
pytest --ignore=test_invites_api.py --ignore=test_workspace_api.py
```

To run only a specific module:

```bash
pytest test_app.py
```

If you want to run the live-server tests, start the backend first, then:

```bash
pytest test_invites_api.py test_workspace_api.py
```

---

## 7. Lint and format (ruff)

The backend is linted with [ruff](https://docs.astral.sh/ruff/). Config lives in
`backend/ruff.toml`, and CI runs `ruff check .` as its own job — so a lint error
blocks the PR, not just the reviewer's patience.

```bash
ruff check            # lint (what CI enforces)
ruff check --fix      # lint + autofix
```

Run both from `backend/`: that is where `ruff.toml` is, and a repo-root `ruff check .`
picks up no config at all while also linting `.worktrees/` checkouts.

`ruff format` is a local convenience and is **not** gated: the tree is not
format-clean today (`ruff format --check` reports 69 files, ~2000 lines), so
gating it would bury real changes under whitespace. Do not reformat files your
PR does not otherwise touch.

**Pre-commit hook (recommended):** add this to your local `.git/hooks/pre-commit`
(or use the [pre-commit](https://pre-commit.com) framework with the same command):

```bash
#!/bin/sh
cd backend && .venv/Scripts/ruff check .
```

---

## Common commands

| Command | Purpose |
|---------|---------|
| `alembic heads` | Show current migration heads |
| `alembic history` | Show full migration history |
| `alembic upgrade head` | Apply all pending migrations |
| `python manage.py db-status` | Show alembic heads, applied revisions and per-table row counts |
| `python manage.py stamp [revision]` | Record the revision an existing (unstamped) database is at, without changing its schema |
| `alembic downgrade -1` | Roll back one migration |
| `alembic revision --autogenerate -m "description"` | Generate a new migration |
| `uvicorn app:app --reload` | Start dev server with hot reload |
| `python -m maintenance purge-orphans` | Dry-run sweep: report File rows with missing bytes and orphaned uploads older than 24h. Add `--apply` to drop rows / unlink files (refuses Postgres without `--apply`). |

---

## Project structure

```
backend/
├── app.py                 # FastAPI application, routes, auth, WebSocket
├── database.py            # SQLAlchemy engine, session, Base
├── models.py              # ORM models
├── schemas.py             # Pydantic request/response schemas
├── ai_assist.py           # AI assistant helpers
├── email_sender.py        # Email invite stub
├── maintenance.py         # Ops CLI: python -m maintenance purge-orphans
├── alembic/               # Alembic migrations
│   ├── env.py
│   └── versions/
├── test_*.py              # Pytest test modules
├── smoke_server.py        # Standalone uvicorn runner for smoke tests (port 8001); runs `alembic upgrade head` on stw_smoke.db before serving
├── requirements.txt
├── .env.example
└── README.md
```

---

## Troubleshooting

### `ModuleNotFoundError` on startup

Make sure the virtual environment is activated and dependencies are installed:

```bash
pip install -r requirements.txt
```

### Port 8000 already in use

Find and kill the process, or start on a different port:

```bash
uvicorn app:app --host 127.0.0.1 --port 8001 --reload
```

> [!NOTE]
> If you change the backend port, update `NEXT_PUBLIC_API_URL` in the frontend `.env.local` accordingly.

### Alembic fails with `sqlite` and foreign keys

SQLite is fully supported in local mode. If Alembic ever reports constraint issues, ensure you are running it from the same directory as `alembic.ini`:

```bash
cd /path/to/backend
alembic upgrade head
```

### CORS / cookie issues from the frontend

Ensure `CORS_ORIGINS` includes `http://localhost:3000` and `COOKIE_SECURE=false` in `.env`. The frontend must use `http://localhost:8000` (not an IP address or port-only URL) so that cookies set by the backend stay on the same origin.
