# Demo-data packs for QA

Busy-workspace seed data to make local QA feel like a real, lived-in team.
Touches **no** backend/app code — everything here is new under
`scripts/demo-packs/`.

| File | What it is |
|---|---|
| `make-pack.py` | Stdlib-only generator (deterministic `--seed`). Emits `busy-workspace.json`. |
| `busy-workspace.json` | The pack: 1 workspace, **10 users**, **4 project boards / 200 tasks**, **3 long channels / 135 messages**, **6 wiki pages**. |
| `load-pack.py` | Stdlib-only (`urllib`) loader. POSTs the pack to a running backend, waits out the app's rate limit on `429`, prints/asserts counts. |

All pack users share the throwaway password `DemoQA-2026-pass!`
(local QA only — never use these credentials anywhere real).
The first pack user (`qa-an@example.com`) is invited as `admin`,
the rest as `member`.

## 1. Regenerate the pack (optional)

```bash
python scripts/demo-packs/make-pack.py [--seed 20260912] [--users 10] [--tasks 200]
```

Re-running with the same seed reproduces identical users/projects/tasks/
channels/pages (only `meta.generated_at` reflects the wall clock).

## 2. Load it against a TEMP database

Never load into your dev `stw.db` — spin a throwaway sqlite DB instead:

```bash
# from the repo root, backend on a temp DB (PowerShell / git-bash):
DATABASE_URL="sqlite:///./qa-pack.db" \
  backend/.venv/Scripts/python.exe -m uvicorn app:app --port 8001 --app-dir backend

# in another shell:
python scripts/demo-packs/load-pack.py \
  --api http://127.0.0.1:8001 \
  --email qa-admin@example.com --password 'AdminQA-2026-pass!'
```

The loader registers the admin if new (otherwise logs in), creates the
workspace, invites + accepts all 10 pack users, posts projects/tasks,
channels/messages, and wiki pages — then re-reads everything via the API:

```text
plan: 402 requests, 358 of them writes … against http://127.0.0.1:8001
admin: qa-admin@example.com (id=...)
workspace: Busy Workspace (demo) (slug=busy-workspace-demo id=...)
users: registered=10
projects: 4, tasks posted: 200
channels: 3, messages posted: 135
pages: 6
counts: {"workspace_id": "...", "members": 11, "projects": 4, "tasks": 200, ...}
run: requests=404 rate-limit retries=3 waited=180.0s
OK: demo pack verified (members=11, projects=4, tasks=200, channels=3, messages=135, pages=6)
```

Expected: `members` 11 (admin + 10), `tasks` 200, `channels` 3, `messages` 135,
`pages` 6. The loader re-reads every collection and fails (exit 1) if any count does
not equal the pack's, so a partial load cannot look like a success.

## 3. Rate limiting: a pack load is *supposed* to be throttled

The backend limits its own writes (`backend/rate_limit.py`): 120/min per
identity per route group, 10 logins/min per IP, in a 60-second sliding window.
One pack load makes **402 requests**, and 200 of them are task POSTs from the
single admin identity into the `tasks` bucket — so the 121st task write and every
write after it is refused until the window moves. Re-running the pack inside the
same minute also collides with the 10 logins/min per IP bucket.

This is why the loader treats `429` as a schedule instead of a failure: it reads
the server's `Retry-After`, waits that long, re-sends, and prints what it is doing:

```text
plan: 402 requests, 358 of them writes (busiest bucket: tasks 200 from 1 identity
      against 120 per 60s); expects to be throttled — login: 1 x 60s window,
      tasks: 1 x 60s window, so ~120s of waiting against http://127.0.0.1:8001
rate limited: POST http://127.0.0.1:8001/projects/…/tasks -> 429, waiting 60s
      (retry 1, 60s of 600s used)
...
run: requests=404 rate-limit retries=3 waited=180.0s
counts: {"workspace_id": "…", "members": 11, "projects": 4, "tasks": 200, …}
OK: demo pack verified (members=11, projects=4, tasks=200, channels=3, messages=135, pages=6)
```

The `plan:` number is the count of API operations the pack asks for; a retried
`429` adds one more HTTP send on top of it, which is why `run: requests` can be
larger than `plan:`. So the honest expectation for one load against a
rate-limited server is **~2 minutes**, most of it waiting, not the ~10 seconds of
work. `--max-retry-wait` (default 600 s) caps the total waiting: a server that
refuses forever makes the loader give up with a message instead of hanging.

### The fast path, when you want it

`ENVIRONMENT=dev` does **not** disable the limiter — only `RATELIMIT_ENABLED=0`
does. For a load where waiting is pure overhead (a fresh throwaway DB you are
about to delete), start the target with it off:

```bash
DATABASE_URL="sqlite:///./qa-pack.db" RATELIMIT_ENABLED=0 \
  backend/.venv/Scripts/python.exe -m uvicorn app:app --port 8001 --app-dir backend
```

Prefer leaving it **on** for anything that also serves real traffic — the limiter
off means the seed is not exercising the path your users hit. The loader was made
to survive the limiter rather than to require it off, because a seeding tool that
only works with the app's guardrails removed is a tool that quietly stops working
the moment someone runs it against a normal server; turning the limiter off is a
convenience, not the fix. **No product-side limit was weakened for this** — the
429 rules in `backend/rate_limit.py` apply to the loader exactly as they apply to
everyone else, and `backend/test_demo_pack_loader.py` asserts that (non-429
refusals are still fatal, other traffic still gets denied at the same count).

## 4. Clean up

Stop uvicorn, then delete the temp DB (and any `qa-pack.db*` journals):

```bash
rm -f backend/qa-pack.db*
```

The temp DB is disposable — nothing is merged back.

## Troubleshooting

- `409 Workspace slug already exists` — you loaded twice into the same DB.
  The loader auto-retries once with a unique suffix; prefer a fresh temp DB.
- `401 Invalid email or password` for the admin — wrong `--password` for an
  existing account. Use the original password or a fresh `--email`.
- `422` on register — password must be 8–128 chars and under the 72-byte
  bcrypt limit (plain ASCII is safest).
- `rate limited: … -> 429, waiting 60s` lines — normal on a server with the
  limiter on (see section 3). They are waits, not failures; the run still ends
  with `OK: demo pack verified`. `ERROR: … failed: HTTP 429` means the
  `--max-retry-wait` budget ran out — raise it, or start the target with
  `RATELIMIT_ENABLED=0`.
- The loader exits 1 with `ASSERT FAIL: tasks=N want M` — some writes never
  landed. Re-run against a fresh temp DB; the counts are compared exactly, so a
  short load fails loudly instead of passing a tolerance band.
- Loader exits non-zero with `ASSERT FAIL` — counts drifted; check the
  `counts:` line and backend logs before re-running.
