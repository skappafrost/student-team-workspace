"""Database admin CLI for the STW backend.

Usage (run from the backend/ directory):
    python manage.py seed-demo [--db-url URL] [--fresh]
    python manage.py create-user --email EMAIL --password PASSWORD [--name NAME] [--db-url URL]
    python manage.py reset-password --email EMAIL --password NEW_PASSWORD [--db-url URL]
    python manage.py db-status [--db-url URL]
    python manage.py maintenance [--purge] [--apply] [--dry-run]
        [--retention-days N] [--min-age-hours H] [--upload-dir PATH] [--db-url URL]
    python manage.py maintenance integrity-check [--upload-dir PATH] [--db-url URL]

Only the standard library plus the project's existing dependencies
(SQLAlchemy, alembic, ``app``/``models``/``database``) are used.
No new dependencies are introduced.

``--db-url`` overrides ``DATABASE_URL`` for a single run. A local engine is
built for the override; the global ``database.engine`` is never rebound, so
this module is also safe to drive in-process (tests, REPL).

``maintenance`` wraps :mod:`maintenance` (upload orphan sweeper + retention).
Default is a non-destructive dry-run; ``--purge --apply`` is required for any
deletion. Retention-based deletion is additionally opt-in via the
RETENTION_ENABLED setting (see :mod:`retention`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from sqlalchemy import func, select

import database
import models

# ---------------------------------------------------------------------------
# Seed dataset (fixed identities keep seed-demo idempotent)
# ---------------------------------------------------------------------------

SEED_OWNER_EMAIL = "demo-owner@example.com"
SEED_MEMBER_EMAIL = "demo-member@example.com"
SEED_WORKSPACE_SLUG = "demo"
SEED_WORKSPACE_NAME = "Demo Workspace"

# (project name, [(task title, status, priority, assignee key)])
SEED_PROJECTS: list = [
    (
        "Demo Website",
        [
            ("Design landing page", "todo", "high", "owner"),
            ("Implement auth flow", "doing", "high", "owner"),
            ("Write API docs", "todo", "medium", "member"),
            ("Add dark mode", "backlog", "low", "member"),
            ("Fix mobile nav", "done", "medium", "owner"),
        ],
    ),
    (
        "Demo Mobile App",
        [
            ("Set up push notifications", "todo", "urgent", "member"),
            ("Offline cache", "backlog", "medium", "member"),
            ("Onboarding screens", "doing", "high", "owner"),
            ("Beta release checklist", "todo", "medium", "owner"),
        ],
    ),
]


def _hash_password(password: str) -> str:
    """Hash via the app's helper (single source of truth, no copies).

    Imported lazily so ``--help`` and unrelated subcommands never import
    the FastAPI app — and importing ``app`` only defines routes/helpers,
    it never starts a server (no top-level ``uvicorn.run`` in app.py).
    """
    from app import get_password_hash  # noqa: E402

    return get_password_hash(password)


def _make_session(db_url: str | None):
    """Return (engine, Session) honoring --db-url without rebinding globals."""
    from sqlalchemy.orm import sessionmaker

    eng = database._make_engine(db_url) if db_url else database.engine
    return eng, sessionmaker(bind=eng)()


def _sqlite_file_for_fresh(eng) -> Path:
    """Resolve the sqlite file behind an engine URL, or raise to refuse."""
    url = eng.url
    if url.drivername.split("+")[0] != "sqlite":
        raise ValueError(
            f"--fresh refuses non-sqlite database ({url.drivername}); "
            "point --db-url at a sqlite file instead."
        )
    db_file = url.database
    if not db_file or db_file == ":memory:":
        raise ValueError("--fresh refuses in-memory sqlite (nothing to delete).")
    return Path(db_file)


def cmd_seed_demo(args: argparse.Namespace) -> int:
    from sqlalchemy.orm import sessionmaker

    eng = database._make_engine(args.db_url) if args.db_url else database.engine
    if args.fresh:
        try:
            target = _sqlite_file_for_fresh(eng)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        # Dispose pooled connections before unlinking (Windows file lock).
        eng.dispose()
        if target.exists():
            target.unlink()
            print(f"deleted {target}")
        else:
            print(f"no file at {target} (nothing to delete)")

    models.Base.metadata.create_all(bind=eng)
    db = sessionmaker(bind=eng)()
    try:
        users = {}
        for email, name, role in (
            (SEED_OWNER_EMAIL, "Demo Owner", "owner"),
            (SEED_MEMBER_EMAIL, "Demo Member", "member"),
        ):
            user = db.query(models.User).filter_by(email=email).first()
            if user is None:
                user = models.User(
                    email=email,
                    display_name=name,
                    hashed_password=_hash_password("demo-password-123"),
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                print(f"created user {email} ({role})")
            else:
                print(f"user {email} exists, skipping")
            users[role] = user

        ws = db.query(models.Workspace).filter_by(slug=SEED_WORKSPACE_SLUG).first()
        if ws is None:
            ws = models.Workspace(
                name=SEED_WORKSPACE_NAME,
                slug=SEED_WORKSPACE_SLUG,
                description="Seeded demo workspace (manage.py seed-demo).",
            )
            db.add(ws)
            db.commit()
            db.refresh(ws)
            print(f"created workspace {SEED_WORKSPACE_SLUG}")
        else:
            print(f"workspace {SEED_WORKSPACE_SLUG} exists, skipping")

        for email, role in (
            (SEED_OWNER_EMAIL, "owner"),
            (SEED_MEMBER_EMAIL, "member"),
        ):
            user = users[role]
            link = (
                db.query(models.WorkspaceMember)
                .filter_by(workspace_id=ws.id, user_id=user.id)
                .first()
            )
            if link is None:
                db.add(
                    models.WorkspaceMember(
                        workspace_id=ws.id, user_id=user.id, role=role
                    )
                )
                db.commit()
                print(f"added {email} as {role}")
            else:
                print(f"membership {email} exists, skipping")

        n_tasks = 0
        for proj_name, tasks in SEED_PROJECTS:
            proj = (
                db.query(models.Project)
                .filter_by(workspace_id=ws.id, name=proj_name)
                .first()
            )
            if proj is None:
                proj = models.Project(
                    workspace_id=ws.id,
                    owner_id=users["owner"].id,
                    name=proj_name,
                )
                db.add(proj)
                db.commit()
                db.refresh(proj)
                print(f"created project {proj_name}")
            else:
                print(f"project {proj_name} exists, skipping")
            for position, (title, status, priority, who) in enumerate(tasks):
                task = (
                    db.query(models.Task)
                    .filter_by(project_id=proj.id, title=title)
                    .first()
                )
                if task is None:
                    db.add(
                        models.Task(
                            project_id=proj.id,
                            assignee_id=users[who].id,
                            title=title,
                            status=status,
                            priority=priority,
                            position=float(position),
                        )
                    )
                    n_tasks += 1
            db.commit()
        print(f"seed-demo done: 2 users / 1 workspace / 2 projects / 9 tasks ({n_tasks} tasks inserted)")
    finally:
        db.close()
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    eng, db = _make_session(args.db_url)
    try:
        existing = db.query(models.User).filter_by(email=args.email).first()
        if existing is not None:
            print(f"user {args.email} already exists ({existing.id})")
            return 1
        models.Base.metadata.create_all(bind=eng)
        name = args.name or args.email.split("@", 1)[0]
        try:
            hashed = _hash_password(args.password)
        except Exception as exc:
            detail = getattr(getattr(exc, "detail", None), "__str__", lambda: str(exc))()
            print(f"invalid password: {detail}", file=sys.stderr)
            return 2
        user = models.User(
            email=args.email, display_name=name, hashed_password=hashed
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"created user {user.email} ({user.id})")
        return 0
    finally:
        db.close()


def cmd_reset_password(args: argparse.Namespace) -> int:
    _, db = _make_session(args.db_url)
    try:
        user = db.query(models.User).filter_by(email=args.email).first()
        if user is None:
            print(f"no such user: {args.email}", file=sys.stderr)
            return 2
        try:
            user.hashed_password = _hash_password(args.password)
        except Exception as exc:
            detail = getattr(getattr(exc, "detail", None), "__str__", lambda: str(exc))()
            print(f"invalid password: {detail}", file=sys.stderr)
            return 2
        db.commit()
        print(f"password reset for {args.email}")
        return 0
    finally:
        db.close()


def _alembic_heads() -> list[str]:
    """Current alembic heads from alembic.ini (no DB connection needed)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(Path(__file__).with_name("alembic.ini")))
    return list(ScriptDirectory.from_config(cfg).get_heads())


def cmd_db_status(args: argparse.Namespace) -> int:
    eng, db = _make_session(args.db_url)
    try:
        try:
            heads = _alembic_heads()
        except Exception as exc:  # pragma: no cover - config problem
            print(f"alembic heads: ERROR ({exc})", file=sys.stderr)
            return 2
        print(f"database: {eng.url}")
        print(f"alembic heads ({len(heads)}): {', '.join(heads) if heads else '(none)'}")
        for table in models.Base.metadata.sorted_tables:
            try:
                count = db.execute(select(func.count()).select_from(table)).scalar()
                print(f"{table.name}: {count}")
            except Exception as exc:
                print(f"{table.name}: ERROR ({exc})")
        return 0
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python manage.py",
        description="STW backend database admin CLI.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--db-url",
        default=None,
        help="Override DATABASE_URL for this run (e.g. sqlite:////tmp/demo.db).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed-demo", parents=[common], help="Seed the demo dataset (idempotent).")
    seed.add_argument(
        "--fresh",
        action="store_true",
        help="Delete the sqlite file first. Refuses non-sqlite / in-memory URLs.",
    )

    create = sub.add_parser("create-user", parents=[common], help="Create a user.")
    create.add_argument("--email", required=True)
    create.add_argument("--password", required=True)
    create.add_argument("--name", default=None, help="Display name (default: email prefix).")

    reset = sub.add_parser("reset-password", parents=[common], help="Reset a user's password.")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password", required=True, help="New password.")

    sub.add_parser("db-status", parents=[common], help="Show alembic head + per-table row counts.")

    _add_maintenance_subparser(sub, common)
    return parser


# ---------------------------------------------------------------------------
# maintenance subcommand (delegates to maintenance.py, never reimplements)
# ---------------------------------------------------------------------------

def _add_maintenance_subparser(sub, common) -> None:
    """``python manage.py maintenance ...`` — wraps the maintenance sweeper."""
    maint = sub.add_parser(
        "maintenance",
        parents=[common],
        help="Upload orphan sweeper + retention (dry-run by default).",
    )
    mode = maint.add_mutually_exclusive_group()
    mode.add_argument(
        "--purge",
        action="store_true",
        help="Scan for orphans (dry-run report unless --apply is also given).",
    )
    mode.add_argument(
        "--integrity-check",
        action="store_true",
        help="Read-only reconciliation of File rows vs bytes on disk.",
    )
    maint.add_argument(
        "--apply",
        action="store_true",
        help="Apply the purge (destructive). Default is dry-run (report only).",
    )
    maint.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run flag (default; kept for readability).",
    )
    maint.add_argument(
        "--retention-days",
        type=float,
        default=None,
        help=(
            "Also drop File rows (row + bytes) older than this many days for "
            "this run. 0 disables age-based deletion. Default: the "
            "UPLOAD_RETENTION_DAYS / RETENTION_ENABLED settings (off)."
        ),
    )
    maint.add_argument(
        "--min-age-hours",
        type=float,
        default=None,
        help="Orphan file age threshold in hours (default: 24).",
    )
    maint.add_argument(
        "--upload-dir",
        default=None,
        help="Upload directory to scan (default: app.UPLOAD_DIR).",
    )


def cmd_maintenance(args: argparse.Namespace) -> int:
    """Delegate to maintenance.py without reimplementing the sweeper."""
    import maintenance

    if args.integrity_check:
        return maintenance.main(_maintenance_argv("integrity-check", args))

    # Default and --purge both run purge-orphans; --apply selects the mode.
    argv = ["purge-orphans"]
    if args.apply and not args.purge:
        # --apply without --purge is ambiguous: default to the safe report.
        print(
            "--apply requires --purge (the report-only run is the default). "
            "Re-run with --purge --apply to apply the sweep.",
            file=sys.stderr,
        )
        return 2
    return maintenance.main(_maintenance_argv("purge-orphans", args))


def _maintenance_argv(command: str, args: argparse.Namespace) -> list[str]:
    """Translate manage.py maintenance flags into maintenance.main() argv."""
    argv = [command]
    if command == "purge-orphans":
        if args.apply:
            argv.append("--apply")
        if args.min_age_hours is not None:
            argv += ["--min-age-hours", str(args.min_age_hours)]
        if args.retention_days is not None:
            argv += ["--retention-days", str(args.retention_days)]
    if args.upload_dir is not None:
        argv += ["--upload-dir", str(args.upload_dir)]
    if args.db_url is not None:
        argv += ["--db-url", str(args.db_url)]
    return argv


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "seed-demo":
        return cmd_seed_demo(args)
    if args.command == "create-user":
        return cmd_create_user(args)
    if args.command == "reset-password":
        return cmd_reset_password(args)
    if args.command == "db-status":
        return cmd_db_status(args)
    if args.command == "maintenance":
        return cmd_maintenance(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
