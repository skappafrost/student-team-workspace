# Demo-data packs for QA

Busy-workspace seed data to make local QA feel like a real, lived-in team.
Touches **no** backend/app code — everything here is new under
`scripts/demo-packs/`.

| File | What it is |
|---|---|
| `make-pack.py` | Stdlib-only generator (deterministic `--seed`). Emits `busy-workspace.json`. |
| `busy-workspace.json` | The pack: 1 workspace, **10 users**, **4 project boards / 200 tasks**, **3 long channels / 135 messages**, **6 wiki pages**. |
| `load-pack.py` | Stdlib-only (`urllib`) loader. POSTs the pack to a running backend and prints/asserts counts. |

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
admin: qa-admin@example.com (id=...)
workspace: Busy Workspace (demo) (slug=busy-workspace-demo id=...)
users: registered=10
projects: 4, tasks posted: 200
channels: 3, messages posted: 135
pages: 6
counts: {"workspace_id": "...", "members": 11, "projects": 4, "tasks": 200, ...}
OK: demo pack verified (users>=10, tasks~=200)
```

Expected: `members` 11 (admin + 10), `tasks` 200 (±5 tolerance),
`channels` 3, `messages` 135, `pages` 6.

## 3. Clean up

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
- Loader exits non-zero with `ASSERT FAIL` — counts drifted; check the
  `counts:` line and backend logs before re-running.
