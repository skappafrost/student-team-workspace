# W7-5: Files + Notifications QA Gate Report

**Date:** 2026-09-03  
**Tester:** zen_agent  
**Commit under test:** 783568b (W7-4) + 1451da9 (W7-3)  
**Next.js build output:** standalone, all 27 routes generated successfully  
**Backend:** `http://127.0.0.1:8000` (FastAPI)  

## Build / Typecheck

| Command | Result |
|---------|--------|
| `bun run typecheck` | PASS |
| `bun run build` | PASS |

Build log excerpt:

```
✓ Generating static pages using 3 workers (27/27) in 4.5s
  Finalizing page optimization ...
Route (app)
├ ƒ /api/files
├ ƒ /api/files/[fileId]
├ ƒ /api/notifications
├ ƒ /dashboard/files
├ ƒ /dashboard/notifications
...
```

## Test Environment

- Frontend served at `http://localhost:3001` (production build)
- Backend served at `http://127.0.0.1:8000`
- Test user created via `/auth/register`
- Workspace created via `/workspaces` (slug required)
- `session_token` cookie injected into Playwright context

## Checklist Results

### 1. Register / Login → open /dashboard/files and /dashboard/notifications

**Result:** PASS

- Registration via backend succeeded.
- After setting `session_token`, `/dashboard/files` and `/dashboard/notifications` both loaded without auth errors.
- Files page shows empty state correctly.

Screenshot: `w7-qa-01-files-empty.png`

### 2. Upload file → appears in list

**Result:** PASS (after creating a workspace)

Steps:

1. Register user.
2. Create a workspace (`POST /workspaces` with `name` and `slug`).
3. Open `/dashboard/files`.
4. Click "Upload file" → choose `qa-test-upload.txt` → click "Upload".
5. File appears in the list with name, size (42 B), and upload timestamp.

Screenshot: `w7-qa-02-files-uploaded.png`

> Note: On a fresh registered user with **no workspace**, the proxy currently returns `404 No workspace found` because `/workspaces` returns an empty list. This is a pre-condition for the feature; a UX improvement would be to prompt the user to create/select a workspace.

### 3. Open notifications → new notification appears

**Result:** FAIL

After file upload, navigating to `/dashboard/notifications` shows only skeleton/empty state. The proxy request to the backend returns **404 Not Found**:

```
GET /workspaces/{workspace_id}/notifications  -> 404
{"detail":"Not Found"}
```

OpenAPI inspection of the backend shows no `/workspaces/{id}/notifications` route exists. The notifications UI and proxy are wired correctly, but the backend endpoint is missing.

Screenshot: `w7-qa-03-notifications.png`

### 4. Mark notification read

**Result:** BLOCKED / NOT TESTED

Cannot mark notifications as read because no notifications are returned due to the missing backend endpoint.

### 5. Reload page → state persists

**Result:** PARTIAL

- Files list persists after reload: PASS (backend stores files).
- Notifications state cannot be verified because notifications are not returned.

Screenshot: `w7-qa-05-notifications-reload.png` (still shows empty/skeleton state)

### 6. Visual QA: D1/D3/D4/D6/D8 decisions

**Result:** N/A — no explicit D1/D3/D4/D6/D8 design decision document was provided in this task. Visual QA of the implemented pages shows:

- Consistent dark theme, spacing, and typography with the rest of the dashboard.
- Files page uses a clean table layout with Name / Size / Uploaded at / Actions.
- Upload dialog is clear with drag-and-drop zone and explicit "Upload" action.
- Notifications page header and empty state are styled consistently.

## Issues Found

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| 1 | Backend missing `GET /workspaces/{id}/notifications` | **Blocker** | Notifications page cannot display data; proxy returns 404. |
| 2 | Backend missing notification creation trigger on file upload | Medium | Even if endpoint existed, no notification appears to be generated after file upload. |
| 3 | Fresh users without a workspace see `404 No workspace found` on file upload | Low | UX improvement: guide user to create/select workspace. |
| 4 | Mark-read / mark-all-read cannot be verified | Medium | Blocked by issue #1. |

## API Verification

### File Upload via Proxy (with workspace)

```http
POST /api/files HTTP/1.1
Cookie: session_token=...
Content-Type: multipart/form-data

200 OK
{"id":"...","name":"api-test.txt","size":15,...}
```

### Notifications via Proxy

```http
GET /api/notifications HTTP/1.1
Cookie: session_token=...

404 Not Found
{"error":"{\"detail\":\"Not Found\"}"}
```

## Addendum — W8-1 retest (2026-09-03)

- Proxy updated to use top-level `/notifications` routes (matches backend contract).
- `service.ts` maps `BackendNotification` → UI `Notification` including `file-upload` → `success`.
- Backend already emits `file-upload` notification on successful upload.
- Verification:
  - `bun run typecheck` PASS
  - `bun run build` PASS
  - Backend pytest: 150 passed (excluding live-server tests)
  - E2E (`e2e-notifications.mjs`): 8/8 PASS
    - register → create workspace → upload file → notification appears → mark read → reload persists → mark all read
- Commit: W8-1 result commit TBD

- **Files feature:** PASS — upload, list, and persistence work end-to-end once a workspace exists.
- **Notifications feature:** FAIL — the backend endpoint `/workspaces/{id}/notifications` does not exist, preventing the notifications page from displaying data or testing mark-read/reload persistence.

## Recommendations

1. Add backend routes:
   - `GET /workspaces/{id}/notifications`
   - `PATCH /workspaces/{id}/notifications/{id}/read`
   - `POST /workspaces/{id}/notifications/mark-all-read`
2. Emit a notification when a file is uploaded in the workspace.
3. Consider handling the no-workspace state in the Files UI with a clear CTA to create a workspace.

## Screenshots

- `w7-qa-01-files-empty.png`
- `w7-qa-02-files-uploaded.png`
- `w7-qa-03-notifications.png`
- `w7-qa-05-notifications-reload.png`
