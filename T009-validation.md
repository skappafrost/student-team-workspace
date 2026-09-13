# T009 — bcrypt 72-byte password handling: validation evidence

Task: T009 — Fix bcrypt 72-byte password handling; add password length policy
Branch: feature/T009-fix-bcrypt-72-byte-password-hand
Date: 2026-09-09

## Root cause (confirmed)

- `get_password_hash` truncated `password[:72]` by CHARACTERS then UTF-8
  encoded — multibyte passwords over 72 BYTES raised `ValueError` from bcrypt
  -> 500 on register (Probe-1: 60-char 120-byte password crash).
- `verify_password` passed raw >72-byte input to `bcrypt.checkpw` -> same
  crash on login.

## Changes

- `backend/app.py`
  - New shared helper `_password_bytes(pw) -> bytes`: UTF-8 encode FIRST,
    raise `HTTPException(422, "Password exceeds 72 bytes")` when >72 bytes.
    No silent truncation (truncation creates equivalence classes). Reusable
    by T047 reset.
  - `get_password_hash`: uses the helper; truncation removed.
  - `verify_password`: guarded via the helper (over-limit -> returns False ->
    login 401, never 500); `ValueError` from checkpw caught defensively.
  - `RegisterIn.password`: `Field(min_length=8, max_length=128)` +
    `field_validator` running the byte check -> clean pydantic 422.
- `app/src/app/auth/AuthForm.tsx`: zod sign-up schema mirrors limits
  `.min(8, ...).max(128, 'Password must be at most 128 characters.')`.
- `backend/test_role_matrix.py`: 6 new tests in `TestPublicAuthEndpoints`
  (ascii 8/72 -> 201; e-acute x40 / 80 bytes -> 422; 73 ascii chars -> 422;
  129 chars -> 422; login with >72-byte password -> 401).

## Verification

- pytest (worktree backend, full suite): 158 passed
  (152 baseline + 6 new; 4 pre-existing warnings).
- Live curl against running backend (smoke_server.py on :8001):
  - POST /auth/register ascii password -> 201
  - POST /auth/register 40x e-acute (80 bytes) ->
    422 {"detail": [... "Password exceeds 72 bytes" ...]}
  - POST /auth/login with 80-byte password -> 401 "Invalid email or password"
- Frontend zod (v4.3.6, project version) runtime check of the new schema:
  129 chars -> rejected "Password must be at most 128 characters.";
  72 chars -> accepted; 7 chars -> rejected (min message).
- `bun run typecheck` NOT run: bun not installed on this machine and the app
  has no node_modules. Schema change validated against the real zod@4.3.6
  package instead; change is plain string-schema chaining.

## Edge case: legacy users hashed with old truncation behavior

- Local DBs checked: `backend/stw.db` empty (no tables/users);
  `probe_t001.db` has 2 probe-created users only. No migration needed
  locally.
- Note: bcrypt hash text is always 60 chars, so silent-truncation victims
  (73+ char ASCII passwords under old code) are undetectable from stored
  hashes. Rehash-on-login remains a follow-up candidate only.

## Follow-ups

- T045: CLI reset-password must reuse `_password_bytes` helper.
- T047: reset endpoint reuses the same helper.
