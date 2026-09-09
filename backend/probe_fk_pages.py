"""T014 spot-check: declared FKs on `pages` are real in the SQLite schema."""
import os
import tempfile

from sqlalchemy import text

import database
from database import Base
import models  # noqa: F401

tmp = os.path.join(tempfile.gettempdir(), "t014_fk.db")
if os.path.exists(tmp):
    os.remove(tmp)
engine = database._make_engine("sqlite:///" + tmp.replace("\\", "/"))
Base.metadata.create_all(bind=engine)
with engine.connect() as conn:
    rows = conn.execute(text("PRAGMA foreign_key_list(pages)")).fetchall()
    print("PRAGMA foreign_key_list(pages):")
    for r in rows:
        print("  ", dict(r._mapping))
    fk_on = conn.execute(text("PRAGMA foreign_keys")).scalar()
    print(f"pragma foreign_keys on this connection: {fk_on}")
engine.dispose()
if os.path.exists(tmp):
    os.remove(tmp)
print("OK")
