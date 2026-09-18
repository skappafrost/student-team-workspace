# PERF-BASELINE — STW backend hot read paths (TA6-2)

Baseline load evidence for the five hot read endpoints plus the two found by
the harness. Numbers come from `backend/bench/run_bench.py` (stdlib +
SQLAlchemy only; opt-in, never collected by `pytest`).

**How to reproduce:** `cd backend && python bench/run_bench.py` (or `make bench`).

## Method

* Transport: FastAPI `TestClient` — full middleware, dependency injection,
  serialization and response validation included, so the numbers reflect what
  a real client sees, not just the ORM layer.
* Latency: `time.perf_counter()` around each request; 3 warm-up requests then
  20 timed requests per measurement; p50/p95 are linear-interpolation
  percentiles (stdlib, no numpy).
* Query count: SQLAlchemy `before_cursor_execute` listener on the app engine,
  counted on the final timed request (the same technique as
  `test_nplus1_regression.py` from TA5-1).
* Seed: ORM insert of N rows per endpoint using the model layer; one fresh
  workspace per (endpoint, size) so sizes never share rows.
* Auth: real JWT (`create_access_token`), per repo policy — no test bypass.

## Baseline numbers (SQLite, local, 20 iterations)

Machine: developer workstation. Absolute milliseconds are machine-specific
and not comparable across machines; **query counts and the shape of the
latency curve are the portable signal.**

### 1. Kanban board list — `GET /projects/{id}/tasks`

Board column source. Constant query count = the TA5-1 indexes hold.

| rows | p50 ms | p95 ms | queries |
|------|--------|--------|---------|
| 10   | 9.5    | 10.4   | 3       |
| 100  | 11.7   | 12.9   | 3       |
| 300  | 15.2   | 17.3   | 3       |

### 2. Cross-workspace board list — `GET /users/me/tasks`

Aggregated across all workspaces the user belongs to. Single query — the
per-row Python bucketing (`due` filter) is in-memory after a joined SELECT.

| rows | p50 ms | p95 ms | queries |
|------|--------|--------|---------|
| 10   | 9.0    | 9.4    | 1       |
| 100  | 13.2   | 14.8   | 1       |
| 300  | 25.4   | 28.2   | 1       |

### 3. Channel message list (paginated) — `GET /channels/{id}/messages`

The endpoint TA5-1 fixed (`selectinload(author) + selectinload(reactions)`).
Query count stays flat at 5 as messages grow — the fix is verified by load,
not just by unit assertion.

| rows | p50 ms | p95 ms | queries |
|------|--------|--------|---------|
| 10   | 11.5   | 12.1   | 5       |
| 100  | 14.1   | 16.5   | 5       |
| 500  | 25.2   | 29.5   | 5       |

### 4. Notifications list — `GET /notifications`

| rows | p50 ms | p95 ms | queries |
|------|--------|--------|---------|
| 10   | 8.8    | 17.2*  | 1       |
| 100  | 9.3    | 10.5   | 1       |
| 500  | 17.4   | 22.5   | 1       |

*The n=10 p95 is a first-iteration scheduling artifact (17.2 ms vs a 8.8 ms
p50); the steady-state tail is the n=100 row. Fixed iterations remove it.

### 5. File list — `GET /workspaces/{id}/files`

Metadata only — the endpoint never reads `storage_key` bytes from disk.

| rows | p50 ms | p95 ms | queries |
|------|--------|--------|---------|
| 10   | 11.0   | 11.7   | 4       |
| 100  | 14.7   | 15.9   | 4       |
| 300  | 22.8   | 23.5   | 4       |

### 6. Wiki tree — `GET /workspaces/{id}/pages`

**New pathology found and fixed by this task** (see "Fix" below).

| rows | p50 ms (before) | p50 ms (after) | p95 ms (before) | p95 ms (after) | queries (before) | queries (after) |
|------|-----------------|----------------|-----------------|----------------|------------------|-----------------|
| 10   | 15.8            | 11.8           | 16.4            | 13.0           | 14               | 5               |
| 100  | 62.5            | 14.6           | 67.3            | 17.2           | 104              | 5               |
| 300  | 168.7           | 19.5           | 185.6           | 23.3           | 304              | 5               |

### 7. Wiki flat list — `GET /workspaces/{id}/pages?flat=true`

Same pathology (the flat response is also `PageTreeItem`, so `children` is
serialized for every row too).

| rows | p50 ms (before) | p50 ms (after) | queries (before) | queries (after) |
|------|-----------------|----------------|------------------|-----------------|
| 10   | 15.8            | 11.8           | 14               | 5               |
| 100  | 61.8            | 14.2           | 104              | 5               |
| 300  | 170.3           | 19.3           | 304              | 5               |

## Fix shipped in this task (additive, ~16 lines)

`GET /workspaces/{id}/pages` (tree and flat) returned `PageTreeItem`, whose
`children` array is populated by SQLAlchemy's `Page.children` relationship.
That relationship was lazy-loaded: response serialization touched it once per
returned page, issuing one SELECT per page (N+1). At 300 pages the endpoint
issued 304 statements and took 169 ms p50.

Fix: `selectinload(models.Page.children)` on the list query, batching all
children of the loaded pages into one extra SELECT. Statement count drops to
a constant 5 and p50 at 300 pages drops from 169 ms to 19.5 ms — an **8.7x
speedup** on the worst measured hot path. Response shape is unchanged
(children arrays are still present and populated; verified by
`test_pages_tree_queries.py` and the existing `test_kb_api.py` tree test).

Guarded by a new regression test so the pathology cannot return silently:
`backend/test_pages_tree_queries.py` — seeds 10 vs 100 pages and asserts the
statement count does not grow with rows (same small-vs-large technique as
TA5-1).

## What transfers to CI Postgres, what does not

* **Query counts transfer fully.** They are a property of the query plan the
  ORM emits, not of the engine: `selectinload` behavior, the number of
  statements per request, and the N+1-vs-constant distinction are identical
  on both dialects. This is why the new test runs on both CI jobs.
* **Latency absolute values do NOT transfer.** SQLite is a process-local
  file database with no network hop and a different planner; Postgres adds
  connection + planning overhead per statement but has a real planner with
  better join strategies. Treat the SQLite ms columns as a *regression
  detector on one machine* (before/after on the same run), never as a
  production SLO. The ratio (169 ms → 19.5 ms) is more portable than the
  absolutes.
* **Row-count scaling behavior transfers qualitatively** — an endpoint whose
  latency grows linearly in N on SQLite will grow on Postgres too, but with a
  different constant.
* CI runs the full suite (410 tests) on both SQLite (`backend` job) and
  Postgres (`backend-pg` job); the bench harness itself is opt-in and is not
  part of either job, so CI time is unaffected.

## Follow-ups (documented, not fixed)

These are observations from the baseline, not regressions, and each would
exceed the "additive <= 100 lines" budget for this task:

1. **`GET /users/me/tasks` Python bucketing.** All assigned tasks are loaded
   and the `due` bucket (overdue/today/week/later/none) is filtered in Python
   rather than in SQL. At 300 tasks this is a single 25 ms query that returns
   every row even when only the "today" bucket is requested. Candidate:
   push the date predicates into the query when `due` is set.
2. **No `LIMIT` on unbounded list endpoints.** `GET /notifications`,
   `GET /channels/{id}/messages` and `GET /workspaces/{id}/files` return
   every matching row with no cap. Linear latency growth (8 ms → 17 ms from
   100 → 500 notifications) is the expected symptom. A pagination contract
   (limit/offset, like the one TA3-1 added to other endpoints) is the
   additive fix; it is a response-shape change for clients, so it needs its
   own PR and an `docs/API.md` changelog entry.
3. **`pages` tree is a flat query + Python build.** Even after the eager
   load, the endpoint loads every page in the workspace and builds the tree
   in Python. Fine at 300 pages; at wiki scale (10k+) a recursive CTE
   (Postgres) or a bounded tree depth would be needed.
