# API Quick Reference

Backend: FastAPI on `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and `/redoc`. This file is the curated teammate guide — read this first, use `/docs` for schema details.

> **Accuracy:** every row below was regenerated from the live OpenAPI spec + `routers/` source (16/09/2026, main @ bca27ce, 45 paths). When the code changes, regenerate this file the same way — do not hand-edit individual rows.

## Auth model

- **Register**: `POST /auth/register` `{email, password}` → `201` + `session_token` httpOnly cookie + `TokenOut` body.
- **Login**: `POST /auth/login` `{email, password}` → `200` + `session_token` httpOnly cookie + `TokenOut` body (`access_token`, `refresh_token`, `token_type`, `user`).
- **Every request** after that sends the cookie. Browsers do this automatically; `fetch` from the Next.js app goes through `/api/*` BFF route handlers, which read the cookie and forward it as `Cookie: session_token=...` to the backend.
- **Sessions are revocable**: each login mints an access token carrying a `jti` backed by an `auth_sessions` row. `POST /auth/logout` revokes the current session; `POST /auth/logout-all` revokes every session for the user and returns `{"ok": true, "revoked": <count>}`. A revoked token gets `401` everywhere, including WebSocket auth. Logout is idempotent on an already-dead token.
- `GET /auth/me` → current user profile (`AuthUser`: `id`, `name`, `email`, `role`).
- Access tokens live 1 week (`ACCESS_TOKEN_EXPIRE_MINUTES = 10080`); refresh tokens 7 days.
- Tests authenticate with real JWTs via the `conftest.py` fixtures (`make_user`, `as_user`); the legacy `X-Test-User-*` bypass is gated to test/dev environments.

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
| POST | `/auth/register` | `201`; creates user + session cookie |
| POST | `/auth/login` | `200`; session cookie + tokens |
| POST | `/auth/logout` | Revokes current session; clears cookie; idempotent |
| POST | `/auth/logout-all` | Revokes all sessions; returns `revoked` count |
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
| GET, POST | `/workspaces/{id}/files` | Multipart upload; `?project_id=`/`?task_id=`/`?message_id=` filters on GET |
| GET, PATCH, DELETE | `/files/{id}` | PATCH/DELETE admin+ or uploader; content served from `/uploads/...`; guests cannot upload |

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

## Changelog

Hardening work shipped on `harden/*` branches (draft PRs, reviewer squash-merges). Status as of 16/09/2026.

**Landed on `main`** (squash-merged, in the 45-path surface above):
- **Role matrix + RBAC** (T002, #5) — cross-workspace escalation fixed; `require_permission` map in `authorization.py`.
- **Private channels** (T012, #8) — real `channel_members` gate on private channels (messages, reactions, WS join).
- **SQLite FK enforcement** (T014, #9) — `PRAGMA foreign_keys=ON`.
- **File delete + orphan sweeper** (T040, #7) — delete removes blob + row; `maintenance.py purge-orphans` dry-run sweeper.
- **bcrypt 72-byte** (T009, #6) — passwords over 72 bytes rejected with 422 instead of silent truncation.
- **Test-auth gate** (T003, #1) — `X-Test-User-*` bypass confined to test/dev envs; test fixtures moved to real JWT (T004, #2).
- **Rate limiting** (T3-B02, #78) — sliding window, per-route limiters + fallback write cap.
- **Request logging + healthz** (T3-B03, #79) — request ids, user ids, token-scrubbed logs, `GET /healthz` with db latency.
- **Postgres CI** (T4-E2, #88) — `backend-pg` job; SQLite/PG parity enforced.
- **Audit log** — `GET /workspaces/{id}/audit-log`, admin+, with filters.

**Open `harden/*` PRs** (not yet on `main`; endpoints they add are documented above **only** where the branch is listed as merged — treat the rest as pending):
- #123 `harden/auth-refresh` — `POST /auth/refresh` with single-use rotation + family invalidation.
- #124 `harden/jwt-secret-governance` — refuse startup with the default JWT secret outside dev/test.
- #126 `harden/jti-request-session` — jti revocation routed through the request DB session.
- #128 `harden/upload-ingress` — sanitize, size cap, allow-list, executable sniffing on uploads.
- #130 `harden/uploads-read-auth` — authenticated `/uploads` read path.
- #132 `harden/storage-quota` — per-workspace storage quota at upload time.
- #134 `harden/like-escape-channels-enum` — LIKE wildcard escaping; channel `type` validated.
- #138 `harden/message-fanout` — notification fan-out on message create (DM peer, @mentions, thread replies).
- #148 `harden/nplus1-indexes` — N+1 elimination + FK index plan.
- #149 `harden/observability` — slow-query logging, 5xx counter, `/readyz` readiness.
- #159 `harden/pagination-contract` — uniform `limit`/`offset` on list endpoints.

**Docs-only regeneration note**: this file was rewritten for main @ bca27ce. When a `harden/*` PR above merges, add its row here and drop it from the open list — that is the whole maintenance burden.
