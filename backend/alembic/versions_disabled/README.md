# versions_disabled — archived migrations NOT loaded by Alembic

2026-08-26 (W2-verify t_3adf854f): moved 10b0f2e07f16_initial_migration_stub.py here.
Reason: stub had down_revision=None same as 9926de6687ec_schema_v1 -> TWO head
revisions -> "alembic upgrade head" failed everywhere (Multiple head revisions).
No database still needed the stamp: Postgres stw_db and local SQLite stw.db both
already at 9926de6687ec; test DBs are created fresh. Stub own docstring said it
"must never be run". Restore only if some old DB is stamped 10b0f2e07f16.
