"""FastAPI application factory: composes routers, middleware, static files.

Domain endpoints live in ``routers/``; shared plumbing in ``dependencies.py``
(auth, tokens, resource getters) and ``authorization.py`` (Role, RBAC checks).
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import logging_mw
import rate_limit
from authorization import ROLE_HIERARCHY, Role  # noqa: F401  (re-exported for tests)
from database import Base, engine, get_db  # noqa: F401  (get_db: test override target)
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
    projects,
    tasks,
    workspaces,
)

from config import JWT_SECRET_KEY_DEFAULT, settings


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _require_production_jwt_secret()  # TA1-2: refuse to boot on a known secret
    # Create tables on startup for simplicity in this scaffold stage.
    Base.metadata.create_all(bind=engine)  # TODO(T036)
    if _test_auth_bypass_enabled():
        logging.getLogger(__name__).warning(
            "STW_TEST_AUTH=1 with ENVIRONMENT in {test,dev}: the X-Test-User-* "
            "auth bypass is ENABLED. Never run with this combination outside tests."
        )
    yield


app = FastAPI(title="Student Team Workspace API", lifespan=lifespan)

logger = logging.getLogger("stw")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
