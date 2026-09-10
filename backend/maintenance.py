"""Maintenance CLI for the STW backend.

Usage:
    python -m maintenance purge-orphans [--apply] [--upload-dir PATH] [--db-url URL]

Reclaims disk space from orphaned uploads and repairs File rows whose bytes
are missing (which would otherwise break downloads with a 500):

- Rows whose storage bytes are gone  -> row is dropped (report first)
- Files on disk with no File row, older than 24h -> bytes are unlinked (report first)

Safety: the sweeper defaults to dry-run (report only) and refuses to run
against a PostgreSQL database unless --apply is passed explicitly, so a
production URL can never be touched by accident.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import app as app_module
import database
import models
from sqlalchemy import inspect

logger = logging.getLogger("maintenance")

DEFAULT_ORPHAN_AGE_HOURS = 24.0
POSTGRES_PREFIXES = ("postgres://", "postgresql://", "postgres+")

Report = dict


def _is_postgres_url(url: str) -> bool:
    return url.startswith(POSTGRES_PREFIXES)


def purge_orphans(
    db,
    upload_dir: Path,
    apply: bool = False,
    min_age: Optional[timedelta] = None,
) -> Report:
    """Scan upload state and report (or repair) orphans.

    Returns a report dict with:

    - missing_bytes_rows: [(file_id, storage_key)] rows whose bytes are gone
    - orphan_files: storage keys on disk with no row, older than min_age
    - skipped_fresh_files: storage keys on disk with no row, younger than min_age
    - dropped_rows: storage keys whose rows were deleted (only with apply=True)
    - unlinked_files: storage keys unlinked from disk (only with apply=True)
    - unlink_errors: [(storage_key, error)] failed unlinks (Windows edge case)
    - apply: whether changes were applied
    """
    min_age = min_age or timedelta(hours=DEFAULT_ORPHAN_AGE_HOURS)
    now = datetime.now(timezone.utc)

    rows = db.query(models.File).order_by(models.File.storage_key).all()
    row_keys = {f.storage_key for f in rows}
    rows_by_key = {f.storage_key: f for f in rows}

    # Phase 1: rows pointing at missing bytes -> drop the row (broken download).
    missing_bytes_rows = sorted(
        [(f.id, f.storage_key) for f in rows if not (upload_dir / f.storage_key).exists()],
        key=lambda item: item[1],
    )

    # Phase 2: bytes on disk with no row, older than min_age -> unlink.
    orphan_files: List[str] = []
    skipped_fresh_files: List[str] = []
    for path in sorted(upload_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name in row_keys:
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if now - mtime >= min_age:
            orphan_files.append(path.name)
        else:
            skipped_fresh_files.append(path.name)

    dropped_rows: List[str] = []
    unlinked_files: List[str] = []
    unlink_errors: List[Tuple[str, str]] = []

    if apply:
        for file_id, storage_key in missing_bytes_rows:
            db.delete(rows_by_key[storage_key])
            dropped_rows.append(storage_key)
        if dropped_rows:
            db.commit()

        for storage_key in orphan_files:
            try:
                (upload_dir / storage_key).unlink()
                unlinked_files.append(storage_key)
            except OSError as exc:
                # Windows: the file may still be held open by a download.
                # Leave it for the next run rather than aborting the sweep.
                logger.warning("Could not unlink %s: %s", storage_key, exc)
                unlink_errors.append((storage_key, str(exc)))

    return {
        "missing_bytes_rows": missing_bytes_rows,
        "orphan_files": orphan_files,
        "skipped_fresh_files": skipped_fresh_files,
        "dropped_rows": dropped_rows,
        "unlinked_files": unlinked_files,
        "unlink_errors": unlink_errors,
        "apply": apply,
    }


def _print_report(report: Report) -> None:
    mode = "apply" if report["apply"] else "dry-run"
    changed = False

    for file_id, storage_key in report["missing_bytes_rows"]:
        changed = True
        verb = "dropped row" if report["apply"] else "would drop row"
        print(f"[{mode}] {verb} {file_id} ({storage_key}): bytes missing on disk")

    for storage_key in report["orphan_files"]:
        changed = True
        verb = "unlinked" if report["apply"] else "would unlink"
        print(f"[{mode}] {verb} {storage_key}: no row and older than 24h")

    for storage_key, error in report["unlink_errors"]:
        print(f"[{mode}] unlink FAILED for {storage_key}: {error}", file=sys.stderr)

    for storage_key in report["skipped_fresh_files"]:
        print(f"[{mode}] kept {storage_key}: no row but younger than 24h")

    if not changed:
        print(f"[{mode}] no orphans found")


def cmd_purge_orphans(args: argparse.Namespace) -> int:
    # Build a LOCAL engine when --db-url is given. Never rebind the global
    # database engine here: this function also runs in-process (tests, REPL)
    # and rebinding would strand later code on the wrong database.
    from sqlalchemy.orm import sessionmaker
    eng = database._make_engine(args.db_url) if args.db_url else database.engine

    effective_url = str(eng.url)
    if _is_postgres_url(effective_url) and not args.apply:
        print(
            "Refusing to run purge-orphans against a PostgreSQL database without "
            "--apply (row-deleting paths are disabled by default). "
            "Re-run with --apply to confirm.",
            file=sys.stderr,
        )
        return 2

    upload_dir = Path(args.upload_dir) if args.upload_dir else app_module.UPLOAD_DIR
    if not upload_dir.is_dir():
        print(
            f"Upload directory {upload_dir} does not exist — refusing to run "
            "(with no bytes on disk every row would look orphaned).",
            file=sys.stderr,
        )
        return 2
    if not inspect(eng).has_table("files"):
        print(
            "The 'files' table was not found in the database — run migrations "
            "(alembic upgrade head) before sweeping.",
            file=sys.stderr,
        )
        return 2

    min_age = timedelta(hours=args.min_age_hours)

    db = sessionmaker(bind=eng)()
    try:
        report = purge_orphans(db, upload_dir, apply=args.apply, min_age=min_age)
    finally:
        db.close()

    _print_report(report)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m maintenance",
        description="STW backend maintenance tasks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    purge = sub.add_parser(
        "purge-orphans",
        help="Drop File rows with missing bytes and unlink old orphaned uploads.",
    )
    purge.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Default is dry-run (report only).",
    )
    purge.add_argument(
        "--upload-dir",
        default=None,
        help="Upload directory to scan (default: app.UPLOAD_DIR).",
    )
    purge.add_argument(
        "--db-url",
        default=None,
        help="Override DATABASE_URL for this run.",
    )
    purge.add_argument(
        "--min-age-hours",
        type=float,
        default=DEFAULT_ORPHAN_AGE_HOURS,
        help="Orphan file age threshold in hours (default: 24).",
    )

    args = parser.parse_args(argv)
    if args.command == "purge-orphans":
        return cmd_purge_orphans(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
