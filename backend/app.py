"""FastAPI application factory: composes routers, middleware, static files.

Domain endpoints live in ``routers/``; shared plumbing in ``dependencies.py``
(auth, tokens, resource getters) and ``authorization.py`` (Role, RBAC checks).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from authorization import Role  # noqa: F401  (re-exported for tests and convenience)
from database import Base, engine, get_db  # noqa: F401  (get_db: test override target)
from dependencies import (  # noqa: F401
    _parse_cors_origins,
    create_access_token,  # re-exported for tests
)
from routers import (
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

app = FastAPI(title="Student Team Workspace API")


# Create tables on startup for simplicity in this scaffold stage.
@app.on_event("startup")
def _create_tables():
    Base.metadata.create_all(bind=engine)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


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
):
    app.include_router(_r)


# Static file serving for uploads
app.mount("/uploads", StaticFiles(directory=str(files.UPLOAD_DIR)), name="uploads")
