# Ops runbook: uploads maintenance & retention

Applies to `backend/` (STW). Everything here is safe by default: **a run never deletes anything unless you pass `--apply`**, and retention-based deletion is additionally opt-in via config.

## TL;DR

From the `backend/` directory:

```bash
# What would be reclaimed? (dry-run, default, touches nothing)
python manage.py maintenance --purge
python manage.py maintenance --integrity-check

# Actually reclaim it
python manage.py maintenance --purge --apply
```

Retention (drop old uploaded files entirely) is off unless you arm it — see below.

## What the sweeper does

`maintenance.py purge_orphans` reconciles the `files` table against the `uploads/` directory:

| Condition | Dry-run | `--apply` |
|---|---|---|
| File **row** whose bytes are missing on disk (download would 500) | reports "would drop row" | drops the row |
| **Bytes** on disk with no row, older than the grace period | reports "would unlink" | unlinks the bytes |
| Bytes on disk with no row, younger than the grace period | "kept" (upload may be in flight) | kept |
| Row older than the retention window, retention armed | reports "would drop row and unlink" | drops row + unlinks bytes |
| Row older than the retention window, retention NOT armed | "kept … RETENTION_ENABLED is off" | kept |
| Row of any age with bytes present, no retention window | kept | kept |

Every run prints a counts line first — the sweep counts everything it would touch *before* deleting anything:

```
[dry-run] counts: 2 missing-bytes rows, 1 orphan files, 0 retention-deleted, 0 retention-skipped (not armed), 1 fresh, 0 rows dropped, 0 files unlinked, 0 unlink errors
```

Guards:

- **Dry-run is the default.** `--apply` is required for any deletion.
- **Postgres guard**: running against a `postgresql://` URL without `--apply` exits 2 with a refusal message — a production URL can never be touched by accident.
- **Missing upload dir** exits 2 (with no bytes on disk, every row would look orphaned).
- **Missing `files` table** exits 2 (run `alembic upgrade head` first).
- **Windows unlink errors** are reported, not fatal: a file held open by a download is left for the next run.
- `--apply` without `--purge` exits 2 (ambiguous); the report-only run is the default.

## Retention policy (env-driven, opt-in)

Config lives in `config.py` (`Settings`, loaded via pydantic-settings → `.env` / environment):

| Env var | Default | Meaning |
|---|---|---|
| `UPLOAD_RETENTION_DAYS` | `0` | Age threshold for the whole File lifecycle (row + bytes). `0` = no age-based deletion. |
| `ORPHAN_MIN_AGE_HOURS` | `24.0` | Grace period a rowless upload survives on disk before it counts as an orphan. |
| `RETENTION_ENABLED` | `false` | Master switch for retention-based deletion. Off = old files are reported, never deleted. |

`retention.py` is the single place that translates settings → thresholds (`retention_enabled()`, `retention_cutoff()`, `orphan_min_age()`).

To enable a 90-day upload retention:

```bash
export RETENTION_ENABLED=1
export UPLOAD_RETENTION_DAYS=90
python manage.py maintenance --purge --apply
```

A one-off override that ignores the setting (arms + sets the window for this run only):

```bash
python manage.py maintenance --purge --apply --retention-days 90
```

`--retention-days 0` explicitly means "keep everything".

## Integrity check

```bash
python manage.py maintenance --integrity-check
```

Read-only reconciliation of File rows vs bytes on disk: reports rows pointing at missing bytes and orphaned bytes with no row. Never mutates — it runs the sweeper with `apply=False` and ignores `--apply`. Use it for monitoring/alerting, or before a deploy to see whether a purge would reclaim anything.

## Scheduling

Run dry-run daily (cheap, read-only) and `--purge --apply` weekly:

```bash
# crontab example (adjust path + user)
0 3 * * *  cd /app/backend && python manage.py maintenance --purge --apply >> /var/log/stw-maintenance.log 2>&1
```

The sweeper is idempotent — running it twice does nothing the second time. Windows runs may report unlink errors for files held open by in-flight downloads; those are retried automatically on the next run.

## Direct module access

```python
import maintenance
report = maintenance.integrity_check(db, upload_dir)          # read-only
report = maintenance.purge_orphans(db, upload_dir, apply=True)
maintenance._summary(report)                                   # scalar counts
```

`integrity_check` is guaranteed read-only: it delegates to `purge_orphans(..., apply=False)` and never commits.
