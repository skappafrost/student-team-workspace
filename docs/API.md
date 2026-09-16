# API Quick Reference

Backend: FastAPI on `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and `/redoc`. This file is the curated teammate guide — read this first, use `/docs` for schema details.

> **Accuracy:** every row below was regenerated from the live OpenAPI spec + `routers/` source (16/09/2026, main @ bca27ce, 45 paths). When the code changes, regenerate this file the same way — do not hand-edit individual rows.

## Auth model

- **Register**: `POST /auth/register` `{email, password}` → `201` + `session_token` httpOnly cookie + `TokenOut` body.
- **Login**: `POST /auth/login` `{email, password}` → `200` + `session_token` httpOnly cookie + `TokenOut` body (`access_token`, `refresh_token`, `token_type`, `user`).
- **Every request** after that sends the cookie. Browsers do this automatically; `fetch` from the Next.js app goes through `/api/*` BFF route handlers, which read the cookie and forward it as `Cookie: session_token=...` to the backend.
- **Sessions are revocable (S02)**: each login creates an `auth_sessions` row keyed by the JWT `jti`. `POST /auth/logout` revokes the current session; `POST /auth/logout-all` revokes all of the user's sessions. A revoked token gets `401` everywhere, including WebSocket auth.
- `GET /auth/me` → current user profile.
- Tests can also bypass JWT with `X-Test-User-Id` / `X-Test-User-Role` headers, but only when `STW_TEST_AUTH=1` is set in a test/dev environment (off by default).

## Conventions

- **Workspace scoping**: almost every resource lives under `/workspaces/{workspace_id}/...`. Membership is checked per request (`403` if you're not a member, `404` if the thing doesn't exist). Guests (role `guest`) can read but not create messages/events/pages/files.
- **Roles**: `owner > admin > member > guest`. Role changes: `PATCH /workspaces/{id}/members/{user_id}`. Ownership transfer: `POST /workspaces/{id}/transfer-ownership` (owner only).
- **Error envelope**: FastAPI default — `{"detail": "human-readable message"}` with the right status code (400 validation, 401 unauthenticated, 403 forbidden, 404 missing, 409 conflict, 422 bad payload, 429 rate-limited with `Retry-After`). Validation errors use `{"detail": [{"loc": [...], "msg": ..., "type": ...}]}`.
- **Rate limiting**: login 10/min per IP + 5/min per email; register 5/hour; upload 20/hour; AI 30/hour; all other write routes 120/min per identity (sliding window; `429` + `Retry-After`). Set `RATELIMIT_ENABLED=0` to disable.
- **IDs**: UUID strings. Timestamps: ISO-8601 UTC.
- **Pagination**: collection endpoints accept `?limit=` and `?offset=` (see [Pagination](#pagination)).

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
| GET | `/users/me/tasks` | My tasks across workspaces; `?due=overdue|today|week|later|none`, `?status=`, `?limit= ?offset=` |
| GET | `/users/me/export` | JSON download of all my data (S03) |
| DELETE | `/users/me` | Delete account; body `{password}`; anonymizes, purges private data |

### Workspaces, members, invites

| Method | Path | Notes |
|---|---|---|
| GET | `/workspaces/{id}/audit-log` | Admin+; `?verb= ?target_type= ?actor_id= ?q= ?limit= ?offset=` (default 100, max 500) |
| GET, POST | `/workspaces` | List mine / create |
| GET, PATCH, DELETE | `/workspaces/{id}` | |
| GET | `/workspaces/{id}/members` | Admin+; `?limit= ?offset=` |
| PATCH, DELETE | `/workspaces/{id}/members/{user_id}` | Change role / remove |
| GET, POST | `/workspaces/{id}/invites` | GET takes `?limit= ?offset=` (admin+) |
| PATCH, DELETE | `/workspaces/{id}/invites/{invite_id}` | |
| POST | `/invites/accept` | `201`; accept by token |
| POST | `/workspaces/{id}/transfer-ownership` | Owner only |
| GET | `/workspaces/{id}/activity?limit=` | Activity feed (R03): actor, verb, target, ts. Default/max 100 |

### Projects & tasks

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/projects` | GET takes `?limit= ?offset=` |
| GET, PATCH, DELETE | `/projects/{id}` | |
| GET, POST | `/projects/{id}/tasks` | `?status=` filter on GET; `?limit= ?offset=` |
| PATCH, DELETE | `/tasks/{id}` | Assigning a task notifies the assignee (R03) |

### Channels & messages

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/channels` | GET takes `?limit= ?offset=` |
| GET | `/channels/{channel_id}/members` | `?limit= ?offset=` |
| GET, POST | `/channels/{id}/messages` | GET: `?q=` search, `?limit= ?offset=`; new messages broadcast over WS |
| PATCH, DELETE | `/messages/{id}` | |
| POST | `/messages/{id}/reactions` | Toggle emoji reaction |
| GET, POST | `/workspaces/{id}/dms` | Direct messages; GET takes `?limit= ?offset=` |

### Calendar events

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/events` | POST `201` (any member); GET takes `?start=&end=` (ISO dates) |
| GET, PATCH, DELETE | `/events/{id}` | PATCH/DELETE creator or admin+ |

**Recurrence**: events carry `recurrence: none|daily|weekly|monthly` (`EventType`: `deadline|exam|meeting|reminder`). When you pass a `start`/`end` range, recurring events expand into occurrences with `occurrence_id` (`{event_id}@{date}`); monthly clamps to month length (Jan 31 → Feb 28). Without a range you get base events only.

### Wiki pages

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/pages` | `?flat=`, `?search=`, `?recent=`, `?limit=` (recent/search only) |
| GET, PATCH, DELETE | `/workspaces/{id}/pages/{page_id}` | Slug unique per workspace |

### Files

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/files` | GET: `?project_id= ?task_id= ?message_id= ?limit= ?offset=`; POST is multipart upload |
| GET, PATCH, DELETE | `/files/{id}` | File content served from `/uploads/...` |

#### Storage quota (TA2-3)

Each workspace has a storage quota enforced at upload time on `POST /workspaces/{id}/files`: if the workspace's stored bytes (SUM of `files.size_bytes` for that workspace) plus the incoming upload would exceed the limit, the request is rejected with `413` and a `detail` message naming the quota — no row is created, no bytes are written. The check runs before any bytes hit disk. Deleting a file frees its bytes against the quota immediately (the row goes first, bytes unlink best-effort).

- Config: `MAX_WORKSPACE_STORAGE_MB` (default `512`; `0` disables the check). Conventional `Settings` field `max_workspace_storage_mb`, validated by pydantic-settings.
- Quota is **per workspace**: usage in one workspace never blocks uploads to another.
- **Orphaned bytes do not count.** Usage is computed from `files.size_bytes` rows, not raw disk usage. If a delete leaves bytes on disk (Windows lock, crash), those bytes are invisible to the quota until `python -m maintenance purge-orphans --apply` unlinks them — quota enforcement and orphan purging are therefore complementary: the quota caps what the API tracks, the sweeper reclaims what it doesn't.

### Notifications

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/notifications` | GET: `?unread_only=true`, `?limit= ?offset=` |
| GET, PATCH, DELETE | `/notifications/{id}` | PATCH `{read: bool}` |

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

## Pagination

All collection (list) endpoints share one contract — the helper lives in `backend/pagination.py`, new endpoints should reuse it:

- Query params: `?limit=` (1..1000) and `?offset=` (>= 0). Omitted `limit` uses the endpoint's default, which for every paginated list equals the 1000 cap — i.e. the full collection (the BFF clients rely on that); omitted `offset` is 0.
- Hard cap: `limit` above **1000** is rejected with `422` (validation), never silently truncated. Two endpoints keep stricter caps they shipped with: `GET /workspaces/{id}/activity` (default/max 100) and `GET /workspaces/{id}/audit-log` (default 100, max 500).
- Responses stay **bare JSON arrays** (shape frozen — no `{items,total}` envelopes); pages are read with `limit`/`offset` windows over the same ordering each endpoint already uses.
- Ordering is explicit and stable on every paginated list (creation/join time or position), so windows are disjoint and deterministic.
- Endpoints without a collection shape (`/ai/search`, `/users/me/export`, tree-mode `/pages` without `recent`/`search`) are not paginated.

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

## Changelog

### TA4-1 — message notification fan-out (additive)

- `POST /channels/{id}/messages` now creates notifications for other users, using the existing `notify()` service and `NotificationOut` shape (no response-body changes): **DM peer** (type `dm`) when the channel is a DM; **@mentions** (type `mention`) parsed conservatively — a token matches only the FULL display name of a workspace member (no substring/prefix matches; non-members are never resolved); **thread parent author** (type `thread`) when `parent_id` is set. The author never self-notifies, and a user hit by several triggers in one message is notified exactly once (DM wins over mention wins over thread). New notification types `dm` and `thread` are added to `schemas.NotificationType` — additive enum widening; existing types and all payload shapes are unchanged.
- There is no per-user quiet/DND state on the `Notification` model yet (only `read`), so quiet-hours suppression is intentionally out of scope here.
