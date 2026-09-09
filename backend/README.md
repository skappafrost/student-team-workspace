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

On a fresh SQLite file, tables are also auto-created at startup, but running `alembic upgrade head` is the canonical way to ensure the schema matches the codebase.

---

## 5. Start the development server

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

The API will be available at:

- API root: http://127.0.0.1:8000
- OpenAPI docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

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

## Common commands

| Command | Purpose |
|---------|---------|
| `alembic heads` | Show current migration heads |
| `alembic history` | Show full migration history |
| `alembic upgrade head` | Apply all pending migrations |
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
├── smoke_server.py        # Standalone uvicorn runner for smoke tests (port 8001)
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
