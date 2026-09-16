"""Shared pagination contract for list endpoints.

Contract (see docs/API.md, section "Pagination"):

* Collection endpoints accept the same optional query params everywhere:
  ``limit`` (1..MAX_LIST_LIMIT) and ``offset`` (>= 0).
* Existing response shapes are frozen: endpoints still return a bare top-level
  JSON array of the same objects. This module never wraps responses.
* The default page size equals the hard cap (MAX_LIST_LIMIT), so callers that
  pass no ``limit`` keep seeing the full collection (today's behaviour for the
  frozen BFF clients) while pathological unbounded fetches are still capped.
* Endpoints that already shipped a smaller ``limit`` (activity feed, audit
  log) keep their own default/cap — pass them to :func:`parse_list_params`.

Callers pass the raw query values through :func:`parse_list_params`, which
clamps and returns plain ints.
"""


from fastapi import Query

#: Hard ceiling for any client-supplied ``limit``. Requests above this are
#: rejected with 422 by the query validator.
MAX_LIST_LIMIT = 1000

#: Default page size for endpoints that did not ship one. Equal to the cap so
#: omitting ``limit`` returns the whole collection (up to MAX_LIST_LIMIT).
DEFAULT_LIST_LIMIT = MAX_LIST_LIMIT


def limit_query(description: str = "Maximum number of items to return.") -> int | None:
    """Optional ``limit`` query param (None = endpoint default / unbounded)."""
    return Query(default=None, ge=1, le=MAX_LIST_LIMIT, description=description)


def offset_query(description: str = "Number of items to skip.") -> int | None:
    """Optional ``offset`` query param (None = 0)."""
    return Query(default=None, ge=0, description=description)


def parse_list_params(
    limit: int | None,
    offset: int | None,
    *,
    default: int | None = DEFAULT_LIST_LIMIT,
    max_limit: int = MAX_LIST_LIMIT,
) -> tuple[int | None, int]:
    """Normalize client pagination into (limit, offset).

    * ``limit=None`` resolves to ``default`` (which may itself be ``None`` for
      endpoints that intentionally return the full collection).
    * ``limit`` is clamped into ``[1, max_limit]``; ``offset`` into ``[0, +inf)``.
    """
    if limit is None:
        limit = default
    if limit is not None:
        limit = max(1, min(limit, max_limit))
    return limit, max(offset or 0, 0)
