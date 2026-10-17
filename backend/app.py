"""FastAPI application factory: composes routers, middleware, static files.

Domain endpoints live in ``routers/``; shared plumbing in ``dependencies.py``
(auth, tokens, resource getters) and ``authorization.py`` (Role, RBAC checks).
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # noqa: F401  (re-exported for tests)

import logging_mw
import rate_limit
from authorization import ROLE_HIERARCHY, Role  # noqa: F401  (re-exported for tests)
from config import JWT_SECRET_KEY_DEFAULT, settings
from database import Base, get_db  # noqa: F401  (Base for tests, get_db: test override target)
from dependencies import (  # noqa: F401  (re-exported for tests and convenience)
    _decode_token,
    _parse_cors_origins,
    _test_auth_bypass_enabled,
    _utcnow,
    create_access_token,
    get_password_hash,
    verify_password,
)
from routers import (
    account,
    ai,
    auth,
    channels,
    events,
    files,
    invites,
    members,
    messages,
    notifications,
    pages,
    presence,
    projects,
    tasks,
    workspaces,
)


def _require_production_jwt_secret() -> None:
    """Refuse to boot with a forgeable JWT secret (TA1-2).

    The shipped default (and any blank value) is public knowledge, so tokens
    signed with it can be forged by anyone. Outside dev/test mode — same
    ``ENVIRONMENT`` convention as ``_test_auth_bypass_enabled`` (unset or any
    other value = production) — startup aborts instead of silently running
    with a known key. Reads env at startup time, not import time, so tests
    can monkeypatch it.
    """
    environment = os.getenv("ENVIRONMENT", "").strip()
    if environment in {"test", "dev"}:
        return
    secret = (settings.jwt_secret_key or "").strip()
    if not secret or secret == JWT_SECRET_KEY_DEFAULT:
        raise RuntimeError(
            "Cấu hình không an toàn: JWT_SECRET_KEY vẫn là giá trị mặc định "
            "(hoặc để trống) khi chạy ở chế độ production. Bất kỳ ai cũng có "
            "thể giả mạo token phiên đăng nhập. Hãy đặt JWT_SECRET_KEY thành "
            "một chuỗi ngẫu nhiên dài (ví dụ: python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\") rồi khởi động lại. Chỉ có thể "
            "chạy với secret mặc định khi ENVIRONMENT=test hoặc ENVIRONMENT=dev."
        )


#: uvicorn pings each WebSocket every ``ws_ping_interval`` seconds and fails the
#: connection when no pong arrives within ``ws_ping_timeout`` (both default 20.0,
#: and neither is configured anywhere here). A browser cannot answer a ping while
#: the event loop is busy, so blocking work inside an ``async def`` handler shows
#: up first as a socket dying with 1011 — logged by uvicorn at TRACE, i.e.
#: invisibly. Measuring the stall directly is what turns "the socket closed under
#: load" from an observation into a diagnosis.
LOOP_STALL_CHECK_SECONDS = 1.0
LOOP_STALL_WARN_SECONDS = 2.0


async def _loop_stall_watchdog() -> None:
    log = logging.getLogger("stw.loop")
    loop = asyncio.get_running_loop()
    previous = loop.time()
    while True:
        await asyncio.sleep(LOOP_STALL_CHECK_SECONDS)
        now = loop.time()
        drift = now - previous - LOOP_STALL_CHECK_SECONDS
        if drift > LOOP_STALL_WARN_SECONDS:
            log.warning(
                "event loop stalled %.1fs: WebSocket keepalive cannot be answered "
                "while the loop is blocked",
                drift,
            )
        previous = now


@asynccontextmanager
async def lifespan(app: FastAPI):
    _require_production_jwt_secret()  # TA1-2: refuse to boot on a known secret
    # The migration chain is the only schema source: the server builds no tables
    # of its own. A database nobody migrated is not visible at boot — every route
    # but the ones touching a missing table answers fine — so name the state once,
    # while the operator is still reading the log. `/readyz` answers 503 for it.
    # `readiness_report()` blanks `alembic_applied` for an unreachable database too,
    # so the message names both readings instead of blaming the chain for an outage.
    report = logging_mw.readiness_report()
    if report["alembic_applied"] == []:
        logging.getLogger("stw.schema").warning(
            "alembic_version reads as empty: either this database could not be "
            "read at all (/readyz reports db=false, so check DATABASE_URL and "
            "reachability first), or nothing has run `alembic upgrade head` against "
            "it, and the server will not create its own schema. For that second "
            "case, if its tables are already present the database was built by "
            "create_all and needs `python manage.py stamp` before `alembic "
            "upgrade head` can run; on a fresh database `alembic upgrade head` "
            "is the step that was skipped."
        )
    if _test_auth_bypass_enabled():
        logging.getLogger(__name__).warning(
            "STW_TEST_AUTH=1 with ENVIRONMENT in {test,dev}: the X-Test-User-* "
            "auth bypass is ENABLED. Never run with this combination outside tests."
        )
    watchdog = asyncio.create_task(_loop_stall_watchdog())
    try:
        yield
    finally:
        watchdog.cancel()
        with suppress(asyncio.CancelledError):
            await watchdog


app = FastAPI(title="Student Team Workspace API", lifespan=lifespan)

logger = logging.getLogger("stw")

app.add_middleware(
    CORSMiddleware,
    # Was `["*"]`, with `allow_credentials=True` alongside it — a combination
    # browsers reject, and one that made `CORS_ORIGINS` (present in .env.example,
    # docker-compose.yml and config.cors_origin_list()) a key with no effect.
    # `_parse_cors_origins` is the settings-backed list, already imported for this
    # purpose and previously unused.
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(logging_mw.RequestLoggingMiddleware)
app.add_middleware(rate_limit.DefaultWriteLimitMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok"}


logging_mw.register_healthz(app)

for _r in (
    auth.router,
    workspaces.router,
    invites.router,
    members.router,
    channels.router,
    messages.router,
    projects.router,
    tasks.router,
    events.router,
    pages.router,
    files.router,
    notifications.router,
    presence.router,
    ai.router,
    account.router,
):
    app.include_router(_r)


# Canonical upload directory. Tests and maintenance.py patch/read
# ``app.UPLOAD_DIR``; routers/files.py resolves it lazily from here so
# monkeypatching works across the router split.
UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Uploads are NOT mounted as static files: routers/files.py serves
# ``GET /uploads/{storage_key}`` with workspace-membership auth (Stage 2.2,
# TA2-2) so a bare URL on the LAN can no longer read workspace bytes.
