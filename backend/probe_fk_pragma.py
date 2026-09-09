"""T014 probe - report SQLite PRAGMA foreign_keys state for app engines.

Run:  python probe_fk_pragma.py

Expect after T014: sqlite_fk_pragma_default: 0, app_conn_fk_pragma: 1,
set_db_url_conn_fk_pragma: 1.
"""

from sqlalchemy import create_engine, text

import database


def _fk_pragma(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("PRAGMA foreign_keys")).scalar()


if __name__ == "__main__":
    default_engine = create_engine("sqlite://")
    print(f"sqlite_fk_pragma_default: {_fk_pragma(default_engine)}")
    print(f"app_conn_fk_pragma: {_fk_pragma(database.engine)}")
    database.set_db_url("sqlite://")
    try:
        print(f"set_db_url_conn_fk_pragma: {_fk_pragma(database.engine)}")
    finally:
        database.set_db_url("sqlite:///./stw.db")
