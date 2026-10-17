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

``migrate_to_head(url)`` is importable rather than a subcommand: it applies the
alembic chain in this process, which is what an entrypoint that opens a database
runs before it serves (see ``smoke_server.py``).

``maintenance`` wraps :mod:`maintenance` (upload orphan sweeper + retention).
Default is a non-destructive dry-run; ``--purge --apply`` is required for any
deletion. Retention-based deletion is additionally opt-in via the
RETENTION_ENABLED setting (see :mod:`retention`).
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
from pathlib import Path

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
            detail = getattr(exc, "detail", None)
            print(f"invalid password: {exc if detail is None else detail}", file=sys.stderr)
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
            detail = getattr(exc, "detail", None)
            print(f"invalid password: {exc if detail is None else detail}", file=sys.stderr)
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


def _alembic_config(db_url: str | None):
    """An alembic Config sharing alembic.ini's script location.

    `%%` doubling is required: `set_main_option` runs the value through
    ConfigParser interpolation, so a password containing `%` would otherwise
    raise rather than connect.
    """
    from alembic.config import Config

    cfg = Config(str(Path(__file__).with_name("alembic.ini")))
    if db_url:
        cfg.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return cfg


@contextlib.contextmanager
def _alembic_target(db_url: str | None):
    """Make `db_url` the database alembic actually opens.

    `alembic/env.py:get_database_url()` resolves the URL itself, in the order
    `DATABASE_URL` → `alembic.ini` → a hardcoded Postgres fallback. So setting
    `sqlalchemy.url` on the Config is not enough: with `DATABASE_URL` present in
    the environment — which it is for every test session, and for any deployed
    container — alembic would silently run against *that* database while the
    command reported success about the one `--db-url` named. Measured exactly
    that way before this helper existed: `stamp --db-url <tmp>` returned 0 and
    wrote `alembic_version` somewhere else.

    Every other command here honours `--db-url` through `_make_session`, so this
    closes the one path where it did not. Without `--db-url` nothing is
    overridden, and alembic keeps its own resolution order.
    """
    if not db_url:
        yield
        return

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _applied_revisions_for(eng) -> list[str]:
    """`alembic_version` rows for *this* engine.

    Not `logging_mw.applied_revisions()`: that reads the global engine, and every
    command here has to honour `--db-url` without rebinding globals — the same
    reason `_make_session` exists.
    """
    from sqlalchemy import text

    try:
        with eng.connect() as conn:
            return sorted(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
    except Exception:
        return []


@contextlib.contextmanager
def _preserving_logging():
    """Keep an in-process alembic call from reconfiguring the whole app's logging.

    `alembic/env.py` runs `fileConfig(alembic.ini)`, and `fileConfig` defaults to
    `disable_existing_loggers=True`: it replaces the root logger's handler list
    and marks every already-created `stw.*` logger disabled. In a terminal that is
    the intended behaviour (conftest's `run_alembic` documents the same choice and
    restores rather than editing `env.py`). In this process it is not: `stamp`
    runs inside a live app/test session, and after it a later `caplog` assertion
    reads `records=[]` for a line that was demonstrably emitted — a silent loss of
    log capture, which is exactly the failure mode that makes a green-looking run
    lie.
    """
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    disabled = {
        name: logger.disabled
        for name, logger in logging.Logger.manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }
    try:
        yield
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        for name, logger in logging.Logger.manager.loggerDict.items():
            if isinstance(logger, logging.Logger) and name in disabled:
                logger.disabled = disabled[name]


def migrate_to_head(db_url: str) -> list[str]:
    """Apply the alembic chain in this process; return the revisions recorded.

    Every entrypoint that opens a database has to migrate it before serving. A
    schema materialised by `Base.metadata.create_all` instead (`conftest.py` per
    test, and any database built while the server still created its own) hides a
    broken migration: the app works anyway, and so do the tests. An entrypoint
    therefore calls this instead of shelling out to `alembic`, and gets the two
    guards `stamp` needs for the same reasons: `_alembic_target` makes the named
    URL the database alembic actually opens, and `_preserving_logging` stops
    `env.py`'s `fileConfig()` from disabling this process's `stw.*` loggers.

    Raises when the chain fails. The failure a caller hits first is an unstamped
    database: tables from `create_all`, no `alembic_version` row, so the first
    unconditional `create_table` in `9926de6687ec_schema_v1.py` dies with
    "table already exists". The repair is `python manage.py stamp --db-url <url>`.
    """
    from alembic import command

    cfg = _alembic_config(db_url)
    with _alembic_target(db_url), _preserving_logging():
        command.upgrade(cfg, "head")

    eng = database._make_engine(db_url)
    try:
        return _applied_revisions_for(eng)
    finally:
        eng.dispose()


def cmd_stamp(args: argparse.Namespace) -> int:
    """Record the revision a database is at, without touching its schema.

    This is the repair for the stuck state `create_all` leaves a database in.
    `conftest.py` builds every test database that way, and so did this server
    until it stopped creating its own schema, so such a database has every table
    and no `alembic_version` row. `alembic upgrade head` then starts from base and
    dies on the first unconditional `create_table` in
    `9926de6687ec_schema_v1.py`, which reads as a broken migration when the actual
    problem is an unstamped database.

    Stamping is a statement of fact, so it refuses when the fact is false: no
    tables at all means the chain should be *applied*, not recorded.
    """
    from sqlalchemy import inspect as sa_inspect

    from alembic import command

    eng = database._make_engine(args.db_url) if args.db_url else database.engine
    tables = set(sa_inspect(eng).get_table_names())
    if not tables:
        print(
            "nothing to stamp: the database has no tables. Run "
            "`alembic upgrade head` against it instead of recording a revision "
            "this schema never reached.",
            file=sys.stderr,
        )
        return 2

    cfg = _alembic_config(args.db_url)
    revision = args.revision or "head"
    with _alembic_target(args.db_url), _preserving_logging():
        command.stamp(cfg, revision)
    applied = _applied_revisions_for(eng)
    print(f"stamped {revision} -> alembic_version: {', '.join(applied) or '(none)'}")
    return 0


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
        applied = _applied_revisions_for(eng)
        if applied:
            print(f"alembic version (applied): {', '.join(applied)}")
        else:
            # The distinguishing case, and the one that looks like a broken
            # migration: tables present, no `alembic_version`.
            print(
                "alembic version (applied): (none) — if the tables below are "
                "present, this database was built by create_all and needs "
                "`python manage.py stamp` before `alembic upgrade head` can run"
            )
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

    stamp = sub.add_parser(
        "stamp",
        parents=[common],
        help="Record the alembic revision a database is at, without changing its schema.",
    )
    stamp.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="Revision to record (default: head).",
    )

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
    if args.command == "stamp":
        return cmd_stamp(args)
    if args.command == "maintenance":
        return cmd_maintenance(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
