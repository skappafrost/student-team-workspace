# API Quick Reference

Backend: FastAPI on `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and `/redoc`. This file is the curated teammate guide — read this first, use `/docs` for schema details.

> **Accuracy:** every row below was regenerated from the live OpenAPI spec + `routers/` source (16/09/2026, main @ bca27ce, 45 paths). When the code changes, regenerate this file the same way — do not hand-edit individual rows.

## Auth model

- **Register**: `POST /auth/register` `{email, password}` → `201` + `session_token` httpOnly cookie + `TokenOut` body.
- **Login**: `POST /auth/login` `{email, password}` → `200` + `session_token` httpOnly cookie + `TokenOut` body (`access_token`, `refresh_token`, `token_type`, `user`).
- **Every request** after that sends the cookie. Browsers do this automatically; `fetch` from the Next.js app goes through `/api/*` BFF route handlers, which read the cookie and forward it as `Cookie: session_token=...` to the backend.
- **Sessions are revocable (S02)**: each login creates an `auth_sessions` row keyed by the JWT `jti`. `POST /auth/logout` revokes the current session; `POST /auth/logout-all` revokes all of the user's sessions. A revoked token gets `401` everywhere, including WebSocket auth.
- **Refresh tokens are revocable + single-use (TA1-1)**: the refresh token returned by register/login shares the same `auth_sessions` row as the access token, so logout/logout-all also kill the refresh token. `POST /auth/refresh` rotates it into a fresh pair; replaying an already-rotated refresh token revokes the whole rotation family (reuse = theft signal).
- `GET /auth/me` → current user profile.
- Tests can bypass JWT with `X-Test-User-Id` / `X-Test-User-Role` headers (test-only path).

### JWT secret governance (TA1-2)

The shipped `JWT_SECRET_KEY` default is public knowledge (it lives in the repo), so the backend **refuses to start** outside `ENVIRONMENT=test/dev` while the secret is still the default or blank — startup aborts with a `RuntimeError` instead of silently signing forgeable tokens. A deployment simply sets `ENVIRONMENT=production` (or leaves it unset) + a strong `JWT_SECRET_KEY`.

**Rotating the secret** (e.g. after a leak, or periodically):

1. Generate a new value: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Update `JWT_SECRET_KEY` in the backend environment/`.env` and restart. There is a single signing key (no keyring), so restart applies it immediately.
3. What it invalidates: **every existing access token and refresh token** stops validating (they were signed with the old key) — all users are effectively logged out and simply log in again. `auth_sessions` rows and revocations (S02) are keyed by `jti` and survive the rotation, so previously revoked tokens stay revoked.
4. Optional cleanup: rows in `auth_sessions` whose tokens can no longer validate are inert; `POST /auth/logout-all` from each account or the existing maintenance script can prune them if desired.

## Conventions

- **Workspace scoping**: almost every resource lives under `/workspaces/{workspace_id}/...`. Membership is checked per request (`403` if you're not a member, `404` if the thing doesn't exist). Guests (role `guest`) can read but not create messages/events/pages/files.
- **Roles**: `owner > admin > member > guest`. Role changes: `PATCH /workspaces/{id}/members/{user_id}`. Ownership transfer: `POST /workspaces/{id}/transfer-ownership` (owner only).
- **Error envelope**: FastAPI default — `{"detail": "human-readable message"}` with the right status code (400 validation, 401 unauthenticated, 403 forbidden, 404 missing, 409 conflict, 422 bad payload, 429 rate-limited with `Retry-After`). Validation errors use `{"detail": [{"loc": [...], "msg": ..., "type": ...}]}`.
- **Rate limiting**: login 10/min per IP + 5/min per email; register 5/hour; upload 20/hour; AI 30/hour; all other write routes 120/min per identity (sliding window; `429` + `Retry-After`). Set `RATELIMIT_ENABLED=0` to disable.
- **IDs**: UUID strings. Timestamps: ISO-8601 UTC.
- **Pagination**: list endpoints return full arrays by default. `GET /workspaces/{id}/audit-log` takes `limit` (default 100, cap 500) + `offset`; `GET /workspaces/{id}/activity` takes `limit` (default 50, cap 100); `GET /workspaces/{id}/pages` takes `limit` (default 10, cap 100) for `recent`/`search` modes.
- **Health**: `GET /health` → `{"status": "ok"}`; `GET /healthz` → `{"status": "ok", "db_latency_ms": <float>}`.

## Endpoint map

### Auth & account

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | Creates user + session cookie |
| POST | `/auth/login` | Session cookie + tokens |
| POST | `/auth/refresh` | Rotates a refresh token into a fresh pair (single-use; replay revokes the family) |
| POST | `/auth/logout` | Revokes current session |
| POST | `/auth/logout-all` | Revokes all sessions (sign out everywhere) |
| GET | `/auth/me` | Current user |
| GET | `/users/me/tasks` | My tasks across workspaces; `?due=overdue\|today\|week\|later\|none`, `?status=` |
| GET | `/users/me/export` | JSON download of all my data (attachment) |
| DELETE | `/users/me` | Body `{password}`; 403 on wrong password; anonymizes + purges private data |

### Workspaces, members, invites

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces` | List mine / create (`201`). POST accepts an optional `?workspace_id=` query param |
| GET, PATCH, DELETE | `/workspaces/{id}` | PATCH admin+ (`workspace.update`); DELETE owner only (`workspace.delete`) |
| GET | `/workspaces/{id}/members` | |
| PATCH, DELETE | `/workspaces/{id}/members/{user_id}` | Change role / remove (admin+) |
| GET, POST | `/workspaces/{id}/invites` | Admin+ to create |
| PATCH, DELETE | `/workspaces/{id}/invites/{invite_id}` | |
| POST | `/invites/accept` | `201`; accept by token |
| POST | `/workspaces/{id}/transfer-ownership` | Owner only |
| GET | `/workspaces/{id}/activity?limit=` | Activity feed, members only; `limit` default 50 cap 100 |
| GET | `/workspaces/{id}/audit-log` | Admin+ only; filters `?verb=&target_type=&actor_id=&q=&limit=&offset=` |

### Projects & tasks

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/projects` | |
| GET, PATCH, DELETE | `/projects/{id}` | PATCH admin+ or project creator; DELETE admin+ or creator |
| GET, POST | `/projects/{id}/tasks` | `?status=` filter on GET; POST `201`; any member creates |
| PATCH, DELETE | `/tasks/{id}` | PATCH any member; DELETE admin+ or assignee/project owner |

### Channels & messages

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/channels` | `type` validated against `general\|project\|private` |
| PATCH | `/channels/{id}` | Manager (admin or creator) only |
| GET, POST | `/channels/{id}/members` | Private channels only; manager only to add (`201`) |
| DELETE | `/channels/{id}/members/{user_id}` | Manager only |
| GET, POST | `/channels/{id}/messages` | POST `201`; broadcasts over WS + creates notifications |
| PATCH, DELETE | `/messages/{id}` | Author only |
| POST | `/messages/{id}/reactions` | Body `{emoji}`; returns `[ReactionSummary]` |
| GET, POST | `/workspaces/{id}/dms` | Direct messages; body `{user_id}` |

### Calendar events

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/events` | POST `201` (any member); GET takes `?start=&end=` (ISO dates) |
| GET, PATCH, DELETE | `/events/{id}` | PATCH/DELETE creator or admin+ |

**Recurrence**: events carry `recurrence: none|daily|weekly|monthly` (`EventType`: `deadline|exam|meeting|reminder`). When you pass a `start`/`end` range, recurring events expand into occurrences with `occurrence_id` (`{event_id}@{date}`); monthly clamps to month length (Jan 31 → Feb 28). Without a range you get base events only.

### Wiki pages

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/pages` | GET: `?flat=true` tree-vs-flat, `?search=`, `?recent=true`, `?limit=` (default 10, max 100) |
| GET, PATCH, DELETE | `/workspaces/{id}/pages/{page_id}` | POST/GET `201`; PATCH/DELETE admin+ or page creator; slug unique per workspace |
| GET | `/workspaces/{id}/pages/{page_id}/backlinks` | Pages linking to this one |
| GET | `/workspaces/{id}/pages/{page_id}/history` | Versions, newest first |
| POST | `/workspaces/{id}/pages/{page_id}/restore/{version}` | Restore a version |

### Files

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/files` | Multipart upload; optional `project_id`/`task_id`/`message_id` links |
| GET, PATCH, DELETE | `/files/{id}` | File metadata |
| GET | `/uploads/{storage_key}` | File content download (member+ role; `attachment` disposition) |

**Uploads are authenticated (Stage 2.2)**: `GET /uploads/{storage_key}` (the `url` field every file record returns) used to be a bare static mount — anyone on the network with a URL could read workspace bytes. It now runs the same access policy as `GET /files/{id}`: anonymous → 401, non-member → 403, guest → 403, revoked session → 401, unknown key → 404. The URL shape is unchanged, so the frontend `downloadFile` path keeps working as-is; curl users must send the session cookie / `Authorization` header.

Upload ingress rules (TA2-1), enforced server-side on `POST /workspaces/{id}/files`:
- **Name sanitization** — traversal (`../`, `..\`, absolute paths) collapses to a flat, ASCII-safe storage key (the on-disk name never contains separators or `..`); control/format characters (ESC, RTL overrides, NUL, CRLF) are stripped from the stored name; Unicode display names (e.g. Vietnamese `Báo cáo.pdf`) are preserved as `name` and NFC-normalized. Very long names are truncated with the extension kept.
- **Size cap** — uploads larger than `MAX_UPLOAD_MB` (default 25 MB, configurable via env following `config.py` pydantic-settings conventions) are rejected with `413` while streaming, before anything is written to disk.
- **Extension allow-list** — images (png/jpg/gif/webp/bmp/heic), documents (pdf/txt/md/csv/rtf/office/odf), media (mp4/mov/webm/mp3/wav/...), archives (zip/tar/gz/7z), data/code artifacts (json/yaml/toml/py/js/ts/.../ipynb). `svg`/`html` are deliberately excluded (stored-XSS via the same-origin `/uploads` static mount); executables/scripts and macro documents are rejected with `415`. A missing extension is also rejected.
- **Content sniffing** — PE (`MZ`), ELF, Mach-O and Java-class magic signatures are rejected with `415` even when the extension/content-type claims otherwise (renamed-executable spoofing).
- **Duplicates** — same content uploaded twice is stored independently (two rows, two blobs, distinct ids). Dedupe-by-content-hash was considered and deferred: file rows support independent rename/relink/delete lifecycles, and refcounted blobs would ripple through delete in three places plus the orphan sweeper — worth a dedicated follow-up if storage cost matters.
- Error codes follow the project envelope: `422` empty file/invalid name, `413` oversize, `415` disallowed type.

#### Storage quota (TA2-3)

Each workspace has a storage quota enforced at upload time on `POST /workspaces/{id}/files`: if the workspace's stored bytes (SUM of `files.size_bytes` for that workspace) plus the incoming upload would exceed the limit, the request is rejected with `413` and a `detail` message naming the quota — no row is created, no bytes are written. The check runs before any bytes hit disk. Deleting a file frees its bytes against the quota immediately (the row goes first, bytes unlink best-effort).

- Config: `MAX_WORKSPACE_STORAGE_MB` (default `512`; `0` disables the check). Conventional `Settings` field `max_workspace_storage_mb`, validated by pydantic-settings.
- Quota is **per workspace**: usage in one workspace never blocks uploads to another.
- **Orphaned bytes do not count.** Usage is computed from `files.size_bytes` rows, not raw disk usage. If a delete leaves bytes on disk (Windows lock, crash), those bytes are invisible to the quota until `python -m maintenance purge-orphans --apply` unlinks them — quota enforcement and orphan purging are therefore complementary: the quota caps what the API tracks, the sweeper reclaims what it doesn't.

### Notifications

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/notifications` | GET `?unread_only=true`; POST creates one (`201`) |
| GET, PATCH, DELETE | `/notifications/{id}` | PATCH `{read: bool}`; DELETE `204` |

### AI

| Method | Path | Notes |
|---|---|---|
| GET | `/ai/search?q=&scope=` | Semantic search; `scope` default `tasks,pages,messages` |
| POST | `/ai/summarize` | Body `{kind: task\|page\|channel, ref_id}`; 422 on other kinds |

### Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/healthz` | `{"status": "ok", "db_latency_ms": <float>}` |

## WebSocket

`GET /ws/channels/{channel_id}?session_token=<token>` — real-time chat. Auth is the same JWT (query param because browsers can't set headers on WS handshakes); the cookie is also accepted. Rejected handshakes close with code `1008` and one of these reasons: `Missing session_token`, `Invalid session_token`, `Guests cannot join channel`, `Not allowed to join this channel`. Revoked sessions are rejected.

Frames:
- plain text → heartbeat, server replies `{"type": "pong", "channel_id": ...}`
- `{"type": "typing"}` → broadcast `{"type": "typing", "channel_id", "user_id", "user_name"}` to the room (excluding sender)
- new messages broadcast `{"type": "new_message", "message": {...}}`

Rooms are in-memory, so run exactly one uvicorn worker.

## Health, readiness & observability

| Endpoint | Meaning | Status codes |
|---|---|---|
| `GET /health` | Legacy liveness, body frozen: `{"status": "ok"}` | always 200 |
| `GET /healthz` | Liveness + cheap DB latency readout: `{status, db_latency_ms, errors_5xx}` | always 200 (`db_latency_ms` may be `null`) |
| `GET /readyz` | Deployment gate: DB answers `SELECT 1` **and** `alembic_version` equals the single declared migration head. Body: `{status, db, db_latency_ms, schema_current, alembic_heads, alembic_applied}` | 200 ready / 503 not ready |

`/readyz` never leaks exception text, connection strings or credentials — only booleans, latencies and revision ids.

Logging (stdlib `logging`, no extra deps):

- Every request logs one line `METHOD path status ms user=<jwt-sub> req=<X-Request-Id>` on logger `stw.requests` (5xx lines are WARNING and carry a running `err5xx=<n>` counter; also exposed on `/healthz` as `errors_5xx`). Query strings, headers and cookies are never logged.
- Statements slower than `SLOW_QUERY_THRESHOLD_MS` (env, default `200`) log `slow_query <ms>ms stmt=<fingerprint>` on logger `stw.db` at WARNING. Fingerprints are whitespace-collapsed, literal-masked and truncated — bound parameters never appear.

## Frontend BFF mapping

The Next.js app never calls the backend directly from the browser. `app/src/app/api/*/route.ts` handlers proxy to the backend with the session cookie. "Current workspace" = first entry of `GET /workspaces` (resolved server-side) — if you add multi-workspace switching, that resolution is the place to change.

| Frontend | Backend |
|---|---|
| `POST /api/auth/session` | `POST /auth/login` or `/auth/register` (body `kind`) |
| `DELETE /api/auth/session` | `POST /auth/logout` |
| `PATCH /api/auth/session` | `POST /auth/logout-all` |
| `GET /api/auth/me` | `GET /auth/me` |
| `GET, POST /api/workspace` | `GET, POST /workspaces` |
| `GET /api/workspace/current` | `GET /workspaces` (first entry) |
| `GET, PATCH, POST /api/workspace/members` | `/workspaces/{id}/members...` |
| `GET, POST, PATCH, DELETE /api/workspace/invites` | `/workspaces/{id}/invites...` |
| `GET /api/workspace/audit-log` | `GET /workspaces/{id}/audit-log` (filters forwarded) |
| `GET /api/tasks/mine` | `GET /users/me/tasks` |
| `GET, POST, PATCH, DELETE /api/tasks` | `/projects/{id}/tasks` + `/tasks/{id}` (requires `?project_id=` on GET) |
| `GET, POST /api/channels` | `/workspaces/{id}/channels` |
| `GET, POST /api/channels/{channelId}/messages` | `/channels/{id}/messages` |
| `POST /api/messages/{messageId}/reactions` | `POST /messages/{id}/reactions` |
| `GET, POST /api/dms` | `/workspaces/{id}/dms` |
| `GET, POST /api/events` | `/workspaces/{id}/events` (`start`/`end` forwarded) |
| `GET, POST /api/pages` + `/api/pages/{pageId}` | `/workspaces/{id}/pages...` |
| `GET /api/pages/{pageId}/history` + `POST` (restore) | `/workspaces/{id}/pages/{id}/history` and `.../restore/{version}` |
| `GET /api/pages/{pageId}/backlinks` | `/workspaces/{id}/pages/{id}/backlinks` |
| `GET, POST /api/files` + `/api/files/{fileId}` | `/workspaces/{id}/files` + `/files/{id}` |
| `GET, PATCH /api/notifications` | `/notifications` |
| `POST /api/notifications` (`{action: "mark-all-read"}`) | proxies to `POST /notifications/mark-all-read` — **no such backend route exists** (backend has only `POST /notifications` and `GET/PATCH/DELETE /notifications/{id}`); currently fails with 405. Known gap, candidate for a future harden PR. |
| `GET /api/ai/search` | `GET /ai/search` (`q`, `scope` forwarded) |
| `POST /api/ai/summarize` | `POST /ai/summarize` |
| `GET /api/activity` | `GET /workspaces/{first}/activity` |
| `GET /api/account` / `DELETE /api/account` | `GET /users/me/export` / `DELETE /users/me` |

The BFF resolves "current workspace" as the first entry of `GET /workspaces` — if you add multi-workspace switching, that resolution is the place to change.

## Token refresh (TA1-1)

`POST /auth/refresh` with JSON body `{"refresh_token": "<jwt>"}` → same shape as login: `{access_token, refresh_token, token_type: "bearer", user}` (+ rotated `session_token` httpOnly cookie).

Rotation policy:

- **Bound sessions**: a refresh token carries the same `jti` as the access token minted by the same login/register, both backed by one `auth_sessions` row. Consequence: `POST /auth/logout`, `POST /auth/logout-all` and account deletion revoke the refresh token too. Refresh tokens no longer survive logout.
- **Single use**: each successful `/auth/refresh` marks the old row rotated+revoked and mints a successor row with a fresh `jti`, chained to the same `family_id`. The presented refresh token can never be used twice.
- **Reuse detection / family invalidation**: replaying an already-rotated refresh token is treated as token theft — the entire rotation family (every successor row, every access+refresh pair minted from that login) is revoked and the request gets `401`. A concurrent double-spend of the same refresh token can only ever let one request win; the loser triggers the family kill.
- **Plain 401, no family action**: expired, malformed, cross-user (signed `sub` ≠ row owner), unknown `jti`, revoked-but-not-rotated tokens, and pre-TA1-1 jti-less refresh tokens. An access token presented as a refresh token is likewise `401` (the `type` claim must be `refresh`).
- Response shapes of existing endpoints are unchanged; `/auth/refresh` is a new endpoint and defines its own shape (deliberately identical to login's `TokenOut`).

## Changelog

- **TA1-1 (harden/auth-refresh)**: added `POST /auth/refresh` with single-use rotation and family invalidation on replay; refresh tokens now share the session row (`jti`) with their access token, so logout/logout-all revoke them; new `auth_sessions.family_id` + `auth_sessions.rotated` columns (migration `a1f1_refresh_rotation`). No existing endpoint changed shape.

