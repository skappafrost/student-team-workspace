"""Standalone uvicorn runner for smoke tests on port 8001 (see backend/README.md)."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./stw_smoke.db"

import uvicorn

from app import app
from database import DATABASE_URL
from manage import migrate_to_head

if __name__ == "__main__":
    # Migrate before the server binds. A smoke run that only reaches `/health`
    # proves the port is listening, not that the schema is there: on an empty
    # file every real route 500s while the probe stays green, which is how a
    # broken migration stays invisible behind a passing smoke test.
    migrate_to_head(DATABASE_URL)
    uvicorn.run(app, host="127.0.0.1", port=8001)
