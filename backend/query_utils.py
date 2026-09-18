"""Shared SQL LIKE-pattern helpers (TA3-2).

User-supplied search terms are interpolated into ``%...%`` LIKE patterns.
Without escaping, a term containing ``%`` or ``_`` acts as a SQL wildcard:
searching ``50%`` would also match ``50 dollars``, and ``A_B`` would match
``AxB``. These helpers escape the wildcards so they match literally on every
dialect (SQLite + PostgreSQL).

Usage::

    from query_utils import contains_pattern, LIKE_ESCAPE

    db.query(Page).filter(Page.title.ilike(contains_pattern(term),
                                            escape=LIKE_ESCAPE))
"""

LIKE_ESCAPE = "\\"
"""Escape character passed to SQLAlchemy's ``ilike(escape=...)``."""

_ESC = LIKE_ESCAPE


def escape_like(term: str) -> str:
    """Escape ``%``, ``_`` and the escape char itself in ``term``.

    The result, embedded in a LIKE pattern and used with
    ``ilike(..., escape=LIKE_ESCAPE)``, matches ``term`` literally.
    """
    return (
        term.replace(_ESC, _ESC + _ESC)
        .replace("%", _ESC + "%")
        .replace("_", _ESC + "_")
    )


def contains_pattern(term: str) -> str:
    """Build a substring (``%term%``) LIKE pattern with wildcards escaped."""
    return f"%{escape_like(term)}%"
