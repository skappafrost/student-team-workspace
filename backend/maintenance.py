"""Maintenance CLI for the STW backend.

Usage:
    python -m maintenance purge-orphans [--apply] [--upload-dir PATH] [--db-url URL]
    python -m maintenance integrity-check [--upload-dir PATH] [--db-url URL]

Reclaims disk space from orphaned uploads and repairs File rows whose bytes
are missing (which would otherwise break downloads with a 500):

- Rows whose storage bytes are gone  -> row is dropped (report first)
- Files on disk with no File row, older than the grace period -> bytes are unlinked (report first)
- Rows older than the retention window -> row + bytes dropped (report first)

Safety: the sweeper defaults to dry-run (report only) and refuses to run
against a PostgreSQL database unless --apply is passed explicitly, so a
production URL can never be touched by accident. Retention-based deletion is
additionally opt-in via the RETENTION_ENABLED setting (see retention.py).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import inspect

import app as app_module
import database
import models
import retention

logger = logging.getLogger("maintenance")

DEFAULT_ORPHAN_AGE_HOURS = 24.0
POSTGRES_PREFIXES = ("postgres://", "postgresql://", "postgres+")

Report = dict[str, object]
Counts = dict[str, int]


def _is_postgres_url(url: str) -> bool:
    return url.startswith(POSTGRES_PREFIXES)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _storage_mtime(path: Path) -> datetime:
    """File mtime as a tz-aware UTC datetime."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _to_aware(value: datetime | None) -> datetime | None:
    """Normalize a stored timestamp to tz-aware UTC.

    SQLAlchemy's ``DateTime(timezone=True)`` round-trips naive values on
    SQLite (the stored value is whatever was passed, minus tzinfo) and
    aware values on PostgreSQL, so comparisons must normalize first.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _summary(report: Report) -> Counts:
    """Scalar counts for a report (lists -> lengths)."""
    return {
        "missing_bytes_rows": len(report["missing_bytes_rows"]),
        "orphan_files": len(report["orphan_files"]),
        "retention_rows": len(report["retention_rows"]),
        "retention_files": len(report["retention_files"]),
        "retention_skipped": len(report["retention_skipped"]),
        "skipped_fresh_files": len(report["skipped_fresh_files"]),
        "dropped_rows": len(report["dropped_rows"]),
        "unlinked_files": len(report["unlinked_files"]),
        "unlink_errors": len(report["unlink_errors"]),
    }


def integrity_check(db, upload_dir: Path) -> Report:
    """Read-only integrity check: File rows vs bytes on disk.

    Returns a report dict (identical shape to :func:`purge_orphans`, with
    ``apply=False``) describing the reconciliation state. Never mutates.

    - missing_bytes_rows: rows whose storage bytes are gone (broken download)
    - orphan_files: bytes on disk with no row, older than the grace period
    - skipped_fresh_files: bytes on disk with no row, still inside the grace
      period (upload in flight / unclean shutdown mid-handshake)
    - retention_rows: rows older than the retention window (only when armed)
    """
    return purge_orphans(db, upload_dir, apply=False)


def purge_orphans(
    db,
    upload_dir: Path,
    apply: bool = False,
    min_age: timedelta | None = None,
    retention_cutoff: timedelta | None = None,
) -> Report:
    """Scan upload state and report (or repair) orphans.

    The count-first contract: the report is always fully populated with what
    *would* happen before anything is deleted, and the CLI logs the counts.
    See :func:`_summary` for the scalar view used in logs.

    Returns a report dict with:

    - missing_bytes_rows: [(file_id, storage_key)] rows whose bytes are gone
    - orphan_files: storage keys on disk with no row, older than min_age
    - skipped_fresh_files: storage keys on disk with no row, younger than min_age
    - retention_rows: [file_id] rows older than the retention window
    - retention_files: storage keys reclaimed by the retention window
    - retention_skipped: [file_id] older than the window but retention is not armed
    - dropped_rows: storage keys whose rows were deleted (only with apply=True)
    - unlinked_files: storage keys unlinked from disk (only with apply=True)
    - unlink_errors: [(storage_key, error)] failed unlinks (Windows edge case)
    - apply: whether changes were applied
    """
    min_age = min_age or timedelta(hours=DEFAULT_ORPHAN_AGE_HOURS)
    now = _utcnow()

    rows = db.query(models.File).order_by(models.File.storage_key).all()
    row_keys = {f.storage_key for f in rows}
    rows_by_key = {f.storage_key: f for f in rows}

    # Phase 1: rows pointing at missing bytes -> drop the row (broken download).
    missing_bytes_rows = sorted(
        [(f.id, f.storage_key) for f in rows if not (upload_dir / f.storage_key).exists()],
        key=lambda item: item[1],
    )

    # Phase 2: bytes on disk with no row, older than min_age -> unlink.
    orphan_files: list[str] = []
    skipped_fresh_files: list[str] = []
    for path in sorted(upload_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name in row_keys:
            continue
        mtime = _storage_mtime(path)
        if now - mtime >= min_age:
            orphan_files.append(path.name)
        else:
            skipped_fresh_files.append(path.name)

    # Phase 3: retention window over the whole File lifecycle (row + bytes).
    # Disabled by default; only deletes when explicitly armed + apply=True.
    retention_rows: list[str] = []
    retention_files: list[str] = []
    retention_skipped: list[str] = []
    if retention_cutoff is not None:
        cutoff = now - retention_cutoff
        for f in rows:
            created = _to_aware(f.created_at)
            if created is not None and created < cutoff:
                if apply and retention.retention_enabled():
                    retention_rows.append(f.id)
                    retention_files.append(f.storage_key)
                else:
                    retention_skipped.append(f.id)

    dropped_rows: list[str] = []
    unlinked_files: list[str] = []
    unlink_errors: list[tuple[str, str]] = []

    if apply:
        for file_id, storage_key in missing_bytes_rows:
            db.delete(rows_by_key[storage_key])
            dropped_rows.append(storage_key)
        for file_id in retention_rows:
            f = db.get(models.File, file_id)
            if f is None:
                continue
            storage_key = f.storage_key
            db.delete(f)
            dropped_rows.append(storage_key)
        if dropped_rows:
            db.commit()

        for storage_key in orphan_files + retention_files:
            try:
                (upload_dir / storage_key).unlink()
                unlinked_files.append(storage_key)
            except FileNotFoundError:
                # Already gone (retention row shared a key with an orphan, or
                # a concurrent download finished cleanup). Not an error.
                continue
            except OSError as exc:
                # Windows: the file may still be held open by a download.
                # Leave it for the next run rather than aborting the sweep.
                logger.warning("Could not unlink %s: %s", storage_key, str(exc))
                unlink_errors.append((storage_key, str(exc)))

    return {
        "missing_bytes_rows": missing_bytes_rows,
        "orphan_files": orphan_files,
        "retention_rows": retention_rows,
        "retention_files": retention_files,
        "retention_skipped": retention_skipped,
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
        print(f"[{mode}] {verb} {storage_key}: no row and older than the grace period")

    for file_id, storage_key in zip(report["retention_rows"], report["retention_files"]):
        changed = True
        verb = "dropped row and unlinked" if report["apply"] else "would drop row and unlink"
        print(f"[{mode}] {verb} {file_id} ({storage_key}): older than retention window")

    for file_id in report["retention_skipped"]:
        print(
            f"[{mode}] kept {file_id}: older than the retention window but "
            "RETENTION_ENABLED is off (retention purge not armed)"
        )

    for storage_key, error in report["unlink_errors"]:
        print(f"[{mode}] unlink FAILED for {storage_key}: {error}", file=sys.stderr)

    for storage_key in report["skipped_fresh_files"]:
        print(f"[{mode}] kept {storage_key}: no row but younger than the grace period")

    counts = _summary(report)
    print(
        f"[{mode}] counts: "
        f"{counts['missing_bytes_rows']} missing-bytes rows, "
        f"{counts['orphan_files']} orphan files, "
        f"{counts['retention_rows']} retention-deleted, "
        f"{counts['retention_skipped']} retention-skipped (not armed), "
        f"{counts['skipped_fresh_files']} fresh, "
        f"{counts['dropped_rows']} rows dropped, "
        f"{counts['unlinked_files']} files unlinked, "
        f"{counts['unlink_errors']} unlink errors"
    )

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
    # --retention-days on the command line arms + sets the window for this run
    # (operator override). Without it, the deployment setting decides.
    if args.retention_days is not None:
        cutoff = timedelta(days=args.retention_days) if args.retention_days > 0 else None
    else:
        cutoff = retention.retention_cutoff()

    db = sessionmaker(bind=eng)()
    try:
        report = purge_orphans(
            db,
            upload_dir,
            apply=args.apply,
            min_age=min_age,
            retention_cutoff=cutoff,
        )
    finally:
        db.close()

    _print_report(report)
    return 0


def cmd_integrity_check(args: argparse.Namespace) -> int:
    """Read-only reconciliation of File rows vs bytes on disk."""
    from sqlalchemy.orm import sessionmaker

    eng = database._make_engine(args.db_url) if args.db_url else database.engine

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

    db = sessionmaker(bind=eng)()
    try:
        report = integrity_check(db, upload_dir)
    finally:
        db.close()

    _print_report(report)
    return 0


def main(argv: list[str] | None = None) -> int:
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
    purge.add_argument(
        "--retention-days",
        type=float,
        default=None,
        help=(
            "Also drop File rows (row + bytes) older than this many days for "
            "this run. 0 disables age-based deletion. Default: the "
            "UPLOAD_RETENTION_DAYS / RETENTION_ENABLED settings (off)."
        ),
    )

    check = sub.add_parser(
        "integrity-check",
        help="Read-only reconciliation of File rows vs bytes on disk.",
    )
    check.add_argument(
        "--upload-dir",
        default=None,
        help="Upload directory to scan (default: app.UPLOAD_DIR).",
    )
    check.add_argument(
        "--db-url",
        default=None,
        help="Override DATABASE_URL for this run.",
    )

    args = parser.parse_args(argv)
    if args.command == "purge-orphans":
        return cmd_purge_orphans(args)
    if args.command == "integrity-check":
        return cmd_integrity_check(args)
    return 2
