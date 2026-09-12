# API Quick Reference

Backend: FastAPI on `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and `/redoc`. This file is the curated teammate guide — read this first, use `/docs` for schema details.

## Auth model

- **Login**: `POST /auth/login` `{email, password}` → sets `session_token` httpOnly cookie + returns `{access_token, refresh_token, user}`.
- **Every request** after that sends the cookie. Browsers do this automatically; `fetch` from the Next.js app goes through `/api/*` BFF route handlers, which read the cookie and forward it as `Cookie: session_token=...` to the backend.
- **Sessions are revocable (S02)**: each login creates an `auth_sessions` row keyed by the JWT `jti`. `POST /auth/logout` revokes the current session; `POST /auth/logout-all` revokes all of the user's sessions. A revoked token gets `401` everywhere, including WebSocket auth.
- `GET /auth/me` → current user profile.
- Tests can bypass JWT with `X-Test-User-Id` / `X-Test-User-Role` headers (test-only path).

## Conventions

- **Workspace scoping**: almost every resource lives under `/workspaces/{workspace_id}/...`. Membership is checked per request (`403` if you're not a member, `404` if the thing doesn't exist). Guests (role `guest`) can read but not create messages/events/pages/files.
- **Roles**: `owner > admin > member > guest`. Role changes: `PATCH /workspaces/{id}/members/{user_id}`. Ownership transfer: `POST /workspaces/{id}/transfer-ownership`.
- **Error envelope**: FastAPI default — `{"detail": "human-readable message"}` with the right status code (400 validation, 401 unauthenticated, 403 forbidden, 404 missing, 409 conflict, 422 bad payload).
- **IDs**: UUID strings. Timestamps: ISO-8601 UTC.
- **Pagination**: list endpoints currently return full arrays; activity feed takes `?limit=` (default 50, max 100).

## Endpoint map

### Auth & account
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | Creates user + session cookie |
| POST | `/auth/login` | Session cookie + tokens |
| POST | `/auth/logout` | Revokes current session |
| POST | `/auth/logout-all` | Revokes all sessions (sign out everywhere) |
| GET | `/auth/me` | Current user |
| GET | `/users/me/tasks` | My tasks across workspaces; `?due=overdue|today|week|later|none`, `?status=` |
| GET | `/users/me/export` | JSON download of all my data (S03) |
| DELETE | `/users/me` | Delete account; body `{password}`; anonymizes, purges private data |

### Workspaces, members, invites
| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces` | List mine / create |
| GET, PATCH, DELETE | `/workspaces/{id}` | |
| GET | `/workspaces/{id}/members` | |
| PATCH, DELETE | `/workspaces/{id}/members/{user_id}` | Change role / remove |
| GET, POST | `/workspaces/{id}/invites` | |
| PATCH, DELETE | `/workspaces/{id}/invites/{invite_id}` | |
| POST | `/invites/accept` | Accept by token |
| POST | `/workspaces/{id}/transfer-ownership` | Owner only |
| GET | `/workspaces/{id}/activity?limit=` | Activity feed (R03): actor, verb, target, ts |

### Projects & tasks
| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/projects` | |
| GET, PATCH, DELETE | `/projects/{id}` | |
| GET, POST | `/projects/{id}/tasks` | `?status=` filter on GET |
| PATCH, DELETE | `/tasks/{id}` | Assigning a task notifies the assignee (R03) |

### Channels & messages
| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/channels` | |
| GET, POST | `/channels/{id}/messages` | New messages broadcast over WS |
| PATCH, DELETE | `/messages/{id}` | |
| POST | `/messages/{id}/reactions` | Toggle emoji reaction |
| GET, POST | `/workspaces/{id}/dms` | Direct messages |

### Calendar events
| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/events` | GET takes `?start=&end=` (ISO dates) |
| GET, PATCH, DELETE | `/events/{id}` | |

**Recurrence (F08)**: events carry `recurrence: none|daily|weekly|monthly`. When you pass a `start`/`end` range, recurring events expand into occurrences with `occurrence_id` (`{event_id}@{date}`); monthly clamps to month length (Jan 31 → Feb 28). Without a range you get base events only.

### Wiki pages
| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/pages` | `?parent_id=` etc. |
| GET, PATCH, DELETE | `/workspaces/{id}/pages/{page_id}` | Slug unique per workspace |

### Files
| Method | Path | Notes |
|---|---|---|
| GET, POST | `/workspaces/{id}/files` | Multipart upload; optional `project_id`/`task_id`/`message_id` links |
| GET, PATCH, DELETE | `/files/{id}` | File content served from `/uploads/...` |

### Notifications
| Method | Path | Notes |
|---|---|---|
| GET, POST | `/notifications` | `?unread_only=true` |
| GET, PATCH, DELETE | `/notifications/{id}` | PATCH `{read: bool}` |

### AI
| Method | Path | Notes |
|---|---|---|
| GET | `/ai/search?q=` | Semantic search |
| POST | `/ai/summarize` | Summarize content |

## WebSocket

`GET /ws/channels/{channel_id}?session_token=<token>` — real-time chat. Auth is the same JWT (query param because browsers can't set headers on WS handshakes). Revoked sessions (S02) are rejected. Message shape: `{"type": "new_message", "message": {...}}`.

## Frontend BFF mapping

The Next.js app never calls the backend directly from the browser. `app/src/app/api/*/route.ts` handlers proxy to the backend with the session cookie:

| Frontend | Backend |
|---|---|
| `GET /api/tasks/mine` | `GET /users/me/tasks` |
| `GET /api/activity` | `GET /workspaces/{first}/activity` |
| `GET/DELETE /api/account` | `GET /users/me/export` / `DELETE /users/me` |
| `DELETE /api/auth/session` | `POST /auth/logout` |
| `PATCH /api/auth/session` | `POST /auth/logout-all` |

The BFF resolves "current workspace" as the first entry of `GET /workspaces` — if you add multi-workspace switching, that resolution is the place to change.
