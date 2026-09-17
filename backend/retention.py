"""Retention policy settings for the maintenance/ops layer.

All maintenance knobs are env-driven through ``config.settings`` (R02 rule:
import ``settings`` and read attributes instead of calling ``os.getenv``).

Env vars (all optional; defaults are intentionally conservative):

    UPLOAD_RETENTION_DAYS=90        # delete File rows + bytes older than this
    ORPHAN_MIN_AGE_HOURS=24         # grace period for unlinked orphan bytes
    RETENTION_ENABLED=0             # 1/true to enable purge-by-retention

Semantics (deliberate):
- ``upload_retention_days`` bounds the *whole* File lifecycle (row + bytes),
  not the orphan sweeper's grace period. 0 disables age-based deletion.
- ``orphan_min_age_hours`` is the grace period a *rowless* upload survives on
  disk before it is considered an orphan (upload races, retries).
- The destructive path stays opt-in: ``RETENTION_ENABLED`` only arms the
  maintenance run — it never silently deletes anything without --apply.
"""

from __future__ import annotations

from datetime import timedelta

from config import settings


def retention_enabled() -> bool:
    """Whether retention-based purging is armed for this deployment."""
    return bool(settings.retention_enabled)


def retention_cutoff() -> timedelta | None:
    """Age threshold for the whole File lifecycle, or None when disabled.

    Returns None when retention is off or set to 0 (no age-based deletion).
    """
    if not settings.upload_retention_days:
        return None
    return timedelta(days=settings.upload_retention_days)


def orphan_min_age() -> timedelta:
    """Grace period for rowless orphan bytes on disk."""
    return timedelta(hours=settings.orphan_min_age_hours)
