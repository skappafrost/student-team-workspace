# API Quick Reference

Backend: FastAPI on `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and `/redoc`. This file is the curated teammate guide — read this first, use `/docs` for schema details.

> **Accuracy:** every row below was regenerated from the live route table + `routers/` source (19/09/2026; 51 HTTP paths + 2 WebSocket routes). `backend/test_docs_contract.py` fails the build if a route appears in the app without a row here, if a row outlives its route, or if that count stops matching — so regenerate rather than hand-editing individual rows.

## Auth model

- **Register**: `POST /auth/register` `{email, password}` → `201` + `session_token` httpOnly cookie + `TokenOut` body.
- **Login**: `POST /auth/login` `{email, password}` → `200` + `session_token` httpOnly cookie + `TokenOut` body (`access_token`, `refresh_token`, `token_type`, `user`).
- **Every request** after that sends the cookie. Browsers do this automatically; `fetch` from the Next.js app goes through `/api/*` BFF route handlers, which read the cookie and forward it as `Cookie: session_token=...` to the backend.
- **Sessions are revocable (S02)**: each login creates an `auth_sessions` row keyed by the JWT `jti`. `POST /auth/logout` revokes the current session; `POST /auth/logout-all` revokes all of the user's sessions. A revoked token gets `401` everywhere, including WebSocket auth.
- `GET /auth/me` → current user profile.
- Tests can also bypass JWT with `X-Test-User-Id` / `X-Test-User-Role` headers, but only when `STW_TEST_AUTH=1` is set in a test/dev environment (off by default).

## Conventions

- **Workspace scoping**: almost every resource lives under `/workspaces/{workspace_id}/...`. Membership is checked per request (`403` if you're not a member, `404` if the thing doesn't exist). **The guest role is not one uniform rule** — guests pass a plain membership check, so most reads work, but these gates are stricter: creating a channel (`403`, `routers/channels.py:create_channel`), joining a channel socket (`4403`, `routers/channels.py:channel_websocket`), reading uploaded file bytes (`403`, `routers/files.py:_resolve_read_file`), and **presence, where guests are refused on read as well as write** (`403`, `routers/presence.py:_require_member_role`). Anything guarded by `require_permission` needs `member` or above.
- **Citing code from this doc**: use `file:symbol`, not `file:NNN`. Line numbers drift — the presence guest gate moved from `:116` to `:137` without anyone touching the prose that pointed at it.
- **Roles**: `owner > admin > member > guest`. Role changes: `PATCH /workspaces/{id}/members/{user_id}`. Ownership transfer: `POST /workspaces/{id}/transfer-ownership` (owner only).
- **Error envelope**: FastAPI default — `{"detail": "human-readable message"}` with the right status code (400 validation, 401 unauthenticated, 403 forbidden, 404 missing, 409 conflict, 422 bad payload, 429 rate-limited with `Retry-After`). Validation errors use `{"detail": [{"loc": [...], "msg": ..., "type": ...}]}`.
- **Rate limiting**: login 10/min per IP + 5/min per email; register 5/hour; upload 20/hour; AI 30/hour; all other write routes 120/min per identity (sliding window; `429` + `Retry-After`). Set `RATELIMIT_ENABLED=0` to disable.
- **IDs**: UUID strings. **Timestamps: ISO-8601, naive UTC, with no `Z` and no offset** — e.g. `"2026-08-28T09:00:00"`. This is deliberate and cross-engine: `dependencies._utcnow()` stores naive UTC, and `test_dialect_parity.py:216` pins that serialization stays naive on SQLite and PostgreSQL alike. It applies to every timestamp field in the API, presence's `last_seen` included. The trap when consuming it: `new Date("2026-08-28T09:00:00")` in JavaScript parses as **local** time, so append `Z` (or parse with an explicit UTC assumption) at the boundary — otherwise every non-UTC client silently shifts every timestamp.
The BFF resolves "current workspace" as the first entry of `GET /workspaces` — if you add multi-workspace switching, that resolution is the place to change.

## Endpoint map

### Auth & account

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | Creates user + session cookie |
| POST | `/auth/login` | Session cookie + tokens |
| POST | `/auth/logout` | Revokes current session |
| POST | `/auth/logout-all` | Revokes all sessions (sign out everywhere) |
| POST | `/auth/refresh` | Exchanges a refresh token for a new access+refresh pair. Refresh tokens are **single-use**: each call rotates the session row and mints a successor in the same rotation family. Replaying an already-rotated token is treated as theft and revokes the **whole family** (every token from that login) with `401`. Expired/malformed/revoked get a plain `401`. Needs a stable `JWT_SECRET_KEY` across restarts, or outstanding tokens fail to decode. |
| POST | `/auth/ws-ticket` | One-shot WS handshake ticket (TA4-2) |
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
| GET | `/workspaces/{id}/activity?limit=` | Activity feed (R03): actor, verb, target, ts. Default 50, max 100, newest first, no offset |

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
| GET, POST | `/workspaces/{id}/channels` | POST validates `type` against `general/project/private` (422 otherwise; TA3-2) |
| PATCH | `/channels/{id}` | Manager (admin or creator) only |
| GET, POST | `/channels/{id}/members` | Private channels only; manager only to add (`201`) |
| DELETE | `/channels/{id}/members/{user_id}` | Manager only |
| GET, POST | `/channels/{id}/messages` | GET `?q=` substring filter (literal `%`/`_`); POST `201` broadcasts over WS + creates notifications |
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
| GET, POST | `/workspaces/{id}/pages` | GET: `?flat=true` tree-vs-flat, `?search=` substring filter (literal `%`/`_`, TA3-2), `?recent=true`, `?limit=` (default 10, max 100) |
| GET, PATCH, DELETE | `/workspaces/{id}/pages/{page_id}` | POST/GET `201`; PATCH/DELETE admin+ or page creator; slug unique per workspace |
| GET | `/workspaces/{id}/pages/{page_id}/backlinks` | Pages linking to this one |
| GET | `/workspaces/{id}/pages/{page_id}/history` | Versions, newest first |
| POST | `/workspaces/{id}/pages/{page_id}/restore/{version}` | Restore a version |

### Files

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/files` | GET: `?project_id= ?task_id= ?message_id= ?limit= ?offset=`; POST is multipart upload |
| GET, PATCH, DELETE | `/files/{id}` | File content served from `/uploads/...` |
| GET | `/uploads/{storage_key}` | Serves the bytes themselves, authenticated: same policy as `GET /files/{id}` — anonymous `401`, non-member `403`, guest `403`, revoked session `401`, unknown key `404`. Replaced the old unauthenticated `StaticFiles` mount, so any LAN peer with a URL can no longer read another workspace's files. |

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

### Presence

Workspace presence (Task LVT S4/S5). One `PresenceState` row per `(workspace, user)`; a member with no row reads as `offline`, so the feature is additive and needs no backfill.

| Method | Path | Notes |
|---|---|---|
| GET | `/workspaces/{id}/presence` | Every member's presence. **Members only — guests get `403` on read too.** Unknown workspace `404` (checked first, so it wins over `403`). Returns a **bare JSON array**, no `{items,total}` envelope and no `response_model`; **not paginated and not ordered** (see Pagination below) — sort client-side. Item: `{user_id, name, status, status_message, last_seen}` |
| POST | `/workspaces/{id}/presence/me` | Sets the **caller's own** status; there is no route to set someone else's. **`200`, never `201`.** Body `{status, status_message?}` with `status` in `online\|away\|dnd\|offline` (required, non-empty) and `status_message` ≤255 chars — sending `"status_message": null` **clears** it. Side effects beyond the row: broadcasts `presence_update`. It deliberately writes **no** `Activity` entry — the socket path never did, so logging from HTTP made the feed depend on which transport a client happened to use, and `log_activity` has no cooldown, so every status click would permanently occupy one of the eight slots the overview shows. `PresenceState` is the record of status history |

Three details about these two routes that will bite a client:

- **`POST`, not `PUT`.** The route-limiter audit (`test_rate_limit.py`) requires every mutating route, PUT included, to have limiter coverage, and `_WRITE_METHODS` does not treat PUT as a write — so this app has no PUT routes at all.
- **`422` arrives in two different envelopes here.** A shape violation (missing `status`, empty `status`, message over 255) gives FastAPI's standard list form `{"detail": [{"loc": [...], ...}]}`; an unknown `status` **value** is rejected in the service layer and gives the string form `{"detail": "Invalid presence status: sleeping"}`. Branch on the type of `detail`, not just the code.
- **`status` is the derived value, never the stored one.** `effective_status()` demotes an idle `online` row, so a client cannot tell "the user chose away" from "the user went stale" — both read `away`. Do not build a UI that offers to restore a chosen status.

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
- **Exempt, deliberately: `GET /workspaces/{id}/presence`.** The roster is bounded by workspace membership and the client needs the whole set to render "who is online", so paging it would force the BFF to loop for zero benefit — and ordering it (`ORDER BY last_seen`) over a live-changing value makes rows duplicate or skip between windows. It returns every member in one **unordered** bare array; sort client-side.

## Realtime (WebSocket)

Two sockets, one handshake resolver (`dependencies._ws_resolve_user`) and one
close-code table, so authentication and rejection semantics below apply to both:

- `GET /ws/channels/{channel_id}` — chat. Joins **two** rooms for the caller:
  `chan:<channel_id>` (channel frames: messages, typing, reactions) and
  `user:<user_id>` (the caller's own `notification_created` frames).
- `GET /ws/workspaces/{workspace_id}/presence` — presence. Joins **two** rooms:
  `workspace:<workspace_id>` (every presence socket of every member of that
  workspace) and `user:<user_id>`, so a tab that only shows a dashboard still
  hears about its own notifications.

`chan:` and `workspace:` are disjoint: `presence_update` never arrives on the
chat socket, and `new_message`/`typing`/`reaction_update` never arrive on the
presence socket. `user:<user_id>` is deliberately **not** disjoint — both
sockets join it, because either one may be the only connection a tab holds.
A chat page therefore receives each `notification_created` twice, once per
socket: treat the frame as "something changed, refetch" and not as a delta to
merge, or the unread count doubles.

### Authentication (TA4-2)

Precedence, safest first:

1. **Ticket subprotocol (recommended)** — `POST /auth/ws-ticket` (auth'd)
   returns `{"subprotocol": "stw-ws.<ticket>", "expires_in_seconds": 60}`.
   Offer that value as the `Sec-WebSocket-Protocol` header. The ticket is
   one-shot and never appears in a URL or access log. It binds the user the
   REST call authenticated; the WS endpoint does not decode the JWT again.
2. **`session_token` cookie** — the browser default; same JWT as REST.
3. **`?session_token=<token>` query param** — test/legacy fallback. Works,
   but the token lands in server logs, so prefer the ticket in production.

Tickets are enabled unless `ENVIRONMENT` is `test`/`dev` (or
`STW_TEST_AUTH=1`); in those modes the ticket endpoint returns a benign
`stw-ws` value and the cookie path authenticates.

The 101 response names back **exactly** the string the client offered, and
sends no `Sec-WebSocket-Protocol` header at all when the client offered none
(the plain `new WebSocket(url)` browser case). This is not stylistic: RFC 6455
§4.1 step 6 makes a browser fail the handshake if the server names a protocol
it was not offered, and neither Starlette's `accept()` nor uvicorn checks it —
`ws.py:_ws_negotiate_subprotocol` is the single place that decides the value.

### Handshake rejection: what a client can actually observe

Every rejection happens **before** the upgrade is accepted — answering an
unauthenticated `GET /ws/...` with a live socket would put a client into a room it
may not read. That choice has a consequence a client has to design around: **a
close code sent before `accept()` never reaches anyone.** uvicorn's
`websockets_sansio_impl` turns one into `conn.reject(HTTPStatus.FORBIDDEN, "")`,
so the handshake fails as an ordinary HTTP 403 and the code and reason are
discarded. Measured against a running server with a `websockets` client:

| Case | What the client sees |
|---|---|
| no credential | `HTTP 403`, empty body, no close code |
| invalid / expired / revoked token | `HTTP 403`, empty body, no close code |
| channel does not exist | `HTTP 403`, empty body, no close code |
| authenticated but not a member | `HTTP 403` whose body is `{"detail": "Not a workspace member"}` |
| member, valid credential | `101` and a working socket |

That last row's body is not a design. It happens because the membership check
raises an `HTTPException` through a dependency, and Starlette answers an
un-accepted upgrade with an HTTP response, while the endpoints that call
`close(code=…)` themselves get the empty `403` described above. **Do not branch on
it** — it is one code path out of four, and the shape is uvicorn-version
behaviour, not a contract.

In a browser the same failure arrives as whatever that implementation reports for
a refused upgrade — a `WebSocket connection … failed` console line and a `close`
event with no application code. (The text differs per browser and is not part of
this contract; what is measured above is the status.) **There is no way to branch
on 4401 vs 4403 vs 4404 from a browser**, and a client that retries on all of
them will retry forever on a permission problem.

The codes still exist server-side, because the distinction is real and the
endpoint has to decide *something*:

| Code | Meaning |
|---|---|
| 4401 | No credential, or invalid/expired/revoked token. Revoked sessions (S02) land here — the `jti` lookup returns None |
| 4403 | Authenticated but not allowed: not a workspace member, guest role, or no private-channel access (chat). Guests are refused presence here too |
| 4404 | Target does not exist — the channel (chat) or the workspace (presence) |

`backend/test_ws_handshake_rejection.py` pins them at the only layer where they
are visible: the ASGI message the application emits, and that no
`websocket.accept` precedes it. (`WS_BAD_HANDSHAKE` / 4400 was deleted: it was
documented as reserved, no code path could raise it, and a malformed
`Sec-WebSocket-Protocol` offer is simply ignored — see the subprotocol note
above.)

**To learn the reason, ask over HTTP before or after the socket fails.**
`GET /channels/{id}/messages` answers `401` with no valid session, `403` for a
member of another workspace, `404` for a channel that does not exist and `200` for
one the caller can read; `GET /workspaces/{id}/presence` answers `403` for a guest.
Measured against a running server. Those are ordinary responses with ordinary
semantics, and they are the only place the distinction survives.

### Frames — chat socket

Client -> server:

- plain text (e.g. `ping`) -> server replies `{"type": "pong", "channel_id": ...}`
- `{"type": "typing"}` -> broadcast to the channel room, excluding the sender

Server -> client:

- `{"type": "new_message", "message": MessageOut}` — on `POST /channels/{id}/messages`
- `{"type": "message_updated", "message": MessageOut}` — on `PATCH /messages/{id}`,
  the whole corrected row (including its current `reactions`), so a client
  replaces by id instead of guessing what changed. A row the cache has never seen
  is left alone: the list query stays the source of truth.
- `{"type": "message_deleted", "channel_id": ..., "message_ids": [...]}` — on
  `DELETE /messages/{id}`. `message_ids` is every row the request removed, not just
  the one named in the path: `messages.parent_id` is `ondelete="CASCADE"`, so
  deleting a thread parent takes its replies with it and a frame naming only the
  parent would leave every peer rendering ghosts.
- `{"type": "reaction_update", "message_id": ..., "reactions": [...]}` — on reaction toggle
- `{"type": "typing", "channel_id": ..., "user_id": ..., "user_name": ...}`
- `{"type": "notification_created", "notification": NotificationOut}` — pushed to
  the user's `user:<id>` room, which both sockets join, so it arrives once per
  open socket. Same shape as `GET /notifications`, so a client can merge it
  without a second request.

### Frames — presence socket

Client -> server. Text frames only. **Only an explicit status frame may change a
status** — everything else is a keepalive:

- `{"type": "presence", "status": "away", "status_message": "BRB"}` -> stores that
  status and message, broadcasts `presence_update`, replies `{"type": "pong"}`.
  Omitting `status_message` clears it; it must be a string of at most 255 chars.
- `{"type": "presence"}` with no `status` -> **`presence_error` /
  `missing_status`**. It no longer defaults to `online`: a frame that says nothing
  must not overwrite the status the user chose.
- A `status` that is not one of `online|away|dnd|offline`, or not a string ->
  **`presence_error` / `invalid_status`**, and **no `pong`**. A `pong` for a frame
  that changed nothing was how a client learned the wrong thing.
- `{"type": "bye"}` -> the server closes the socket, and the caller's last socket
  going away writes `offline` (the same teardown a close triggers). The bundled
  browser client does not send it — it closes the socket instead, which the
  server sees as a disconnect; `bye` exists for clients that want to say so
  before tearing the transport down.
- **Anything else is a heartbeat**: bare text (`ping`), `{"type": "ping"}`, a JSON
  object with another `type`. It refreshes `last_seen` only — the stored status and
  message are untouched and **nothing is broadcast** — and replies
  `{"type": "pong"}`. Send one well inside `AWAY_AFTER_SECONDS` (300s); the client
  sends every 20s. A tab that never sends anything goes `away` after five minutes
  and its dot greys out while the user is still looking at it.
- Text starting with `{` that is not a valid JSON object -> **`presence_error` /
  `malformed_json`**. It used to be dropped in silence, which hung any client
  waiting for a reply to its own bad frame.

Server -> client. Four kinds:

- `{"type": "presence_update", "workspace_id": ..., "user_id": ..., "name": ..., "status": ..., "status_message": ..., "last_seen": ...}` — the five HTTP item fields plus the workspace id. **Broadcasts include the sender's own socket** (unlike chat's `typing`, which excludes it), so a client must be ready to apply its own change coming back at it.
- `{"type": "pong"}`
- `{"type": "presence_error", "reason": "missing_status" | "invalid_status" | "invalid_status_message" | "malformed_json"}`
- `{"type": "notification_created", "notification": NotificationOut}` — this socket
  is in the caller's `user:<id>` room too, which is what lets a dashboard tab
  with no channel socket react to new activity.

### Connection semantics

On disconnect each socket leaves **every** room it joined in the endpoint's
`finally` — the chat socket the channel room and the user room, the presence
socket the workspace room and the user room. Each peer's send is bounded by
`ws.WS_SEND_TIMEOUT_SECONDS` (2s): a socket that raises, times out, or otherwise
fails to accept a frame is logged and pruned by the broadcast itself, so a
client that dies before its cleanup cannot keep a phantom delivery slot — and
cannot charge its stall to the rest of the room on every later message either.
One wedged peer therefore costs a sender at most 2s, once.

**Presence lifecycle is refcounted per `(workspace, user)`, not per socket.**
The user's *first* presence socket in a workspace writes `online`; a second tab
writes **nothing** (otherwise it would clobber a `dnd` the user chose over HTTP);
`offline` is written only when the *last* socket closes. So closing one browser
tab does not make the user appear offline while they are still looking at the app.

A hard crash never reaches the disconnect handler, so reads decay a *stored*
`online` row on a timer instead: `online` -> `away` after `AWAY_AFTER_SECONDS`
(300s) of no inbound frame, and `online` -> `offline` after
`OFFLINE_AFTER_SECONDS` (1800s). `away`/`dnd`/`offline` never decay — a status a
user chose is kept indefinitely. There is no scheduler, TTL column or sweeper;
both transitions are computed at read/broadcast time from `last_seen`.

Two consequences a client has to live with: the server only refreshes
`last_seen` when a frame arrives, so **an open tab that sends nothing shows as
`away` after five minutes** — send a heartbeat frame well inside 300s. And the
room registry plus the refcount are **in-process memory**, which is correct for
the single uvicorn worker this deployment runs and wrong the moment it is scaled
out; multi-worker fan-out needs a shared store, not more sockets.

A session revoked *after* the handshake is not re-checked: the socket stays open
until it closes. The 4401 refusal guards connection, not the connection's
lifetime (see § Handshake rejection for what a client can observe of it).

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

### Contract status: what is actually on `main`

**Landed on `main`** (squash-merged; every endpoint in the map above exists in the code):
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

**Merged since — the whole hardening wave.** All of these are on `main`; they were listed as "open" here for days after merging, which is exactly how this file lost credibility:
- #123 `POST /auth/refresh` — single-use rotation + family invalidation.
- #124 — refuse startup with the default JWT secret outside dev/test.
- #126 — jti revocation routed through the request DB session.
- #128 — upload sanitize, size cap, MIME allow-list, executable sniffing.
- #130 — authenticated `/uploads` read path (row added to the map above).
- #132 — per-workspace storage quota enforced at upload.
- #134 — LIKE wildcard escaping; channel `type` enum validation.
- #138 — notification fan-out on message create (DM peer, @mentions, thread replies).
- #148 — N+1 elimination + FK indexes.
- #149 — slow-query logging, 5xx counter, `/readyz`.
- #159 — uniform `limit`/`offset` pagination contract.
- #160 — this file regenerated from the live spec, plus `CONTRIBUTING.md` / `PROJECT-STATUS.md`.
- #161 — WebSocket handshake auth + connection semantics.
- #162 — SQLite/PostgreSQL dialect parity suite + timezone normalization.
- #163 — ops maintenance: backup, retention, verification.
- #164 — repeatable load/perf baseline harness.
- #174 — CI coverage floor + RBAC edge regression tests.
- #175 — security regression pack.
- #185 — restored wiring that squash-merges had silently dropped (backend import, `/auth/refresh`, upload path, message-search escaping) and narrowed the `conftest` exception mask that had been hiding it.
- #188 — Alembic single head + `PresenceState` model.
- #189 — presence service: `POST /workspaces/{id}/presence/me`, `GET /workspaces/{id}/presence`, `/ws/workspaces/{id}/presence`.
- #195–#201 — hardening wave: ruff to zero + CI gate, presence socket refcount, this file's route coverage enforced by `test_docs_contract.py`, generic realtime hook (`useRealtimeSocket`).

**Realtime transport fix (#205, #206).** `accept()` used to name `stw-ws` even when the client offered no subprotocol, which RFC 6455 §4.1 step 6 makes a browser fail on — so **no browser socket in this app ever completed a handshake**, while every pytest WS test stayed green because Starlette's `TestClient` records `accepted_subprotocol` without validating it. The reply is now the verbatim offered string, or no header at all. Contract text in § Authentication above is unchanged and was already what the code should have done. No route, status code or payload shape changed. Client-side follow-up in #206: the channel broadcast reaches the author's own socket too, so `chat-page.tsx` dedupes inbound messages by `id` — clients must expect their own writes to come back at them.

**Open PRs** — re-check with `gh pr list --state open`; there were 17 at the time of writing and none of them change the contract above: #85 (dependabot shadcn/react), #121 (T020 search), #137 (client-experience program), #176–#184 (T001, T002, T003, T004, T009, T012, T014, T015, T040 re-submitted — their subjects match behaviour already on `main`, verify each against the landed list before closing), #190–#194 (dependabot: fastapi, httpx, uvicorn, typescript 5.7→7.0, react-table 8→9; the last two are major bumps).

**Maintenance rule**: when your PR changes a route, update the map above **in that PR** — the changelog entry is the second half of the change, not a follow-up.

### TA4-1 — message notification fan-out (additive)

`POST /channels/{id}/messages` now creates notifications it previously swallowed (`_notify_message_fanout`, `routers/messages.py`). Three triggers, one recipient precedence so a user never gets duplicates for the same message: **DM** channels notify the peer (the member who is not the author); **@mentions** notify members whose *full display name* appears as a token — matched as a token, so mentioning `@AliceBlueprint` never resolves to `Alice`; **thread replies** notify the parent message's author. Types come from the existing `NotificationType` vocabulary: `dm`, `mention`, `thread`. Delivery is push-only: `_ws_notify_user` broadcasts to the recipient's `user:<id>` room, which is joined by **both** sockets (`routers/channels.py:channel_websocket` and `routers/presence.py:presence_websocket` each join their own room *and* the user room) — so a client sees `{"type": "notification_created", "notification": NotificationOut}` on whichever it has open, and a chat page that holds both gets it twice. `GET /notifications` is unchanged and stays the source of truth after a reconnect. No response shape changed.

### S6-RT9 — what a refused handshake really looks like (documentation correction)

The handshake section promised that a rejection arrives as a documented `4401`/`4403`/`4404` close code. No client can ever see one. A `websocket.close` sent *before* `accept()` is converted by uvicorn's `websockets_sansio_impl` into `conn.reject(HTTPStatus.FORBIDDEN, "")`, so the upgrade fails as an **HTTP 403** with no code and no reason — measured against a live server with a `websockets` client: no credential, invalid token, unknown channel and non-member all produce `http_status=403, close_code=None`, while a member produces a working socket. `TestClient` raises `WebSocketDisconnect(code=…)` straight from the ASGI message, which is why the whole green WS suite never contradicted the claim; the same wording had also spread into `CONTRIBUTING.md`, `app/env.example.txt`, the host-guard spec and two router docstrings.

Refusing before `accept()` is the correct behaviour and is unchanged. What changed:

- The section now says what a client observes, that the distinction is *not* reachable from a browser, and that the way to learn the reason is an HTTP preflight (`GET /channels/{id}/messages` → `401`/`403`/`404`/`200`, `GET /workspaces/{id}/presence` → `403` for a guest; all measured).
- `WS_BAD_HANDSHAKE` (4400) deleted. It was documented as "reserved, never sent today", no code path could raise it, and a malformed `Sec-WebSocket-Protocol` offer is ignored by design — a dead constant in a contract table is a promise nobody can keep.
- `backend/test_ws_handshake_rejection.py` pins the half that *is* ours: the `websocket.close` message and its code, and that no `websocket.accept` precedes it, for 4401/4403/4404 on both sockets.

No behaviour change: same codes emitted, same refusals, same HTTP statuses.

### S6-RT7 — a reconnecting client refetches, and says so (client behaviour; no contract change)

The server kept the same rules; the browser side of the socket was the gap. Three defects in `app/src/lib/realtime/use-websocket.ts` and its chat consumer:

- **A missed window stayed missed forever.** `useChannelWebSocket` accepted `onOpen` and the chat page passed nothing, so after a reconnect the message list was whatever it had been when the link dropped — with `staleTime: 60s`, no `refetchInterval` and no focus event in a background tab, that state never corrected itself. The channel list is now invalidated on every open, the way presence already did.
- **Silent loss.** `send()` already dropped frames when the socket was not OPEN and nothing was ever rendered, so a dead link looked identical to a quiet channel. The hook now exposes `status` (`idle | connecting | open | reconnecting`) and the chat view shows `Connection lost — reconnecting…` in the `aria-live` row it already uses for typing indicators. `idle` and `connecting` stay quiet: no channel selected and a first attempt are not worth interrupting someone for.
- **Backoff inherited across channels.** The retry delay lived in a ref that survived a `url` change, so after flapping on one channel the *first* failure on a freshly opened one waited 5s instead of 1s. The delay resets when the URL changes.

Also fixed in the same loop: `try` used to wrap `JSON.parse` **and** the consumer call, so any exception thrown by a message handler was caught and labelled a malformed payload. Parsing and dispatch are now separate, so a consumer bug surfaces as what it is.

Verified by `app/tests/reconnect.spec.ts`: it warms the socket with a delivered message, closes the connection from the page, posts while it is down, and asserts the notice appears, the message reaches the tab with **no navigation in between**, and the list was refetched. That last assertion is the load-bearing one — with the `onOpen` invalidation removed the test fails with `fetched 1 times before the drop, 1 after`. A genuine network outage cannot be simulated here: `context.setOffline(true)` leaves an established loopback WebSocket running, and `page.route(…).abort()` does not keep the reconnect down either.

### S6-RT6 — edits and deletes now reach the room (additive frames)

`PATCH /messages/{id}` and `DELETE /messages/{id}` committed and said nothing: only create and react broadcast. A peer kept rendering corrected text as the original, and kept rendering a deleted message, until something else refetched the list. Two new frames close it — `{"type":"message_updated","message":MessageOut}` (the whole corrected row, current `reactions` included, so the client replaces by id rather than guessing what changed) and `{"type":"message_deleted","channel_id":…,"message_ids":[…]}`.

`message_ids` is a list because `messages.parent_id` is `ondelete="CASCADE"`: deleting a thread parent removes its replies in the database, so a frame naming only the parent would leave every peer rendering ghosts. The ids are collected before the delete, while the rows still exist.

No response shape changed; both frames are additive for clients that ignore unknown frame types.

### S6-RT4 — one wedged peer cannot hold the room (latency behaviour change, no shape change)

`ws._ws_broadcast` awaited each peer's `send_text` in a `for` loop with no bound. A half-open TCP does not raise, it stalls, so one wedged socket decided how long every other member waited — and stayed in the room, to be paid for again on the next message. Measured with `backend/bench/ws_stall_probe.py`, peers holding their send for 5s alongside one healthy peer:

| wedged peers | first broadcast | the three that follow |
|---|---|---|
| 1 | 5.00s | 15.03s |
| 3 | 15.02s | 45.08s |

and `POST /channels/{id}/messages` awaits that broadcast on its own request path.

Each send is now wrapped in `asyncio.wait_for(ws.WS_SEND_TIMEOUT_SECONDS = 2.0)`, and a timeout is treated exactly like a send that raised: logged at `WARNING` ("ws send timed out…"), counted as not delivered, pruned from the room. Same probe after: 1 wedged peer costs **2.00s** then **0.00s**; 3 cost **6.03s** then **0.00s** — 2s per wedged peer, once, because they are gone the next time around.

Two things this deliberately does not do:

- **It is not concurrent.** `asyncio.gather` was tried and rejected: gathering wraps each send in a task, which defers the frame by a scheduler tick, and a `TestClient` websocket session runs *each socket on its own portal event loop*. A deferred cross-loop send lands in a peer stream whose receiver has already parked and anyio never wakes it — measured as `test_presence_service.py::test_ws_connect_broadcasts_online` hanging with the peer blocked in `receive_json()`. `wait_for` has been a timeout context around the await since 3.12 rather than a task wrapper, so it keeps the call inline and costs nothing the old code did not already do. The reason is recorded in `_ws_broadcast`'s docstring because someone will reach for `gather` again.
- **The broadcast still sits on the sender's request path.** `create_task` per message would let a later message's frame overtake an earlier one, which the client appends in arrival order; a per-room ordered queue has to survive a test client that builds a new event loop per test. The residual worst case is therefore 2s per wedged peer per message, charged only while some peer is already broken.

### S6-RT3 — presence frames: a keepalive is not a status change (behaviour change)

The presence socket's receive loop seeded `status = "online"` **before** it looked at the payload, so the socket's own documented keepalive overwrote whatever the user had chosen: a bare `ping` wrote `online`, cleared `status_message`, and rebroadcast it to every member socket. A `{"type": "presence"}` with no `status` did the same, and an unknown `status` got a `pong` that claimed success while writing nothing. A non-string `status` raised inside the `frozenset` membership test and killed the socket. Malformed JSON was dropped without any reply, so a client waiting for the answer to its own bad frame hung.

Now (full rules in § Frames — presence socket):

- Only `{"type":"presence","status":"online|away|dnd|offline"}` changes a status; anything else is a heartbeat.
- A heartbeat refreshes `last_seen` and nothing else — no status write, no message clear, **no broadcast** — and answers `pong`. The bundled client sends one every 20s (`app/src/features/presence/hooks/use-presence.tsx`), which is what keeps an idle tab's dot green instead of decaying to `away` after `AWAY_AFTER_SECONDS`.
- Rejections answer `{"type":"presence_error","reason":...}` (`missing_status`, `invalid_status`, `invalid_status_message`, `malformed_json`) instead of a `pong`.
- `{"type":"bye"}` is honoured: the server closes the socket and runs the normal last-socket-`offline` teardown. It was already advertised by the endpoint docstring and never implemented.

Breaking for any client that relied on the permissive form: a frame with a typo'd status now gets an error instead of a `pong`, and `{"type":"presence"}` no longer means "come online". `PresenceRow`, `GET/POST /presence`, and the HTTP `422` envelopes are unchanged.

### TA4-2 — the notification push reaches a socket (fix, no shape change)

`_ws_notify_recipients` (`routers/messages.py`) used to re-derive the recipients a second time and then look each one up with `type == "message"` plus `content LIKE '%<message id>%'`. The fan-out writes types `dm|mention|thread` and prose content that never contains a message id, so the lookup returned nothing on every path and the push silently sent zero frames — while every existing test passed, because they all asserted on the notification *row*. Now `_notify_message_fanout` returns the ids it wrote and `_ws_push_notifications` pushes exactly those rows, which also closes two recipient holes for free: `@mentions` were never pushed at all, and `elif message.parent_id` meant a DM that also mentioned someone delivered one frame instead of two.

Two behaviour changes to plan around:

- A frame that cannot be sent is logged and swallowed. The message is already committed and the sender has their `201`; failing the write over a dead socket would report a delivered message as lost.
- The presence socket joins `user:<user_id>` in addition to `workspace:<workspace_id>`, which is what makes the frame visible to a dashboard tab. `NotificationOut` is unchanged.

### TA3-2 — ilike wildcard escaping + channels type validation
- **Search filters now treat `%` and `_` as literal characters.** `GET /workspaces/{id}/pages?search=`, `GET /channels/{id}/messages?q=` and `GET /workspaces/{id}/audit-log?q=` previously interpolated the raw term into a `%...%` SQL LIKE pattern, so a user searching `50%` also matched `50 dollars` (wildcard `%`) and `A_B` matched `AxB` (wildcard `_`). A shared helper (`backend/query_utils.py`: `escape_like`/`contains_pattern` + `escape=LIKE_ESCAPE`) is now applied at every like/ilike site. Behavior change: searches containing `%`/`_` return exact literal matches on both SQLite and PostgreSQL; plain-text searches are unchanged (still case-insensitive).
- **`POST /workspaces/{id}/channels` validates `type`** against the enum `general|project|private` at the schema layer — unknown types are rejected with 422 (FastAPI's standard validation error envelope) instead of being stored. Valid payloads and the `general` default are unchanged. (Covered by regression tests in `backend/test_query_escapes.py`.)
