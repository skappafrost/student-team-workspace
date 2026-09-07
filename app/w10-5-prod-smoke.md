# W10-5: Production Build Smoke Test

**Run date:** 2026-09-03 (UTC)
**Frontend prod server:** http://127.0.0.1:3001
**Backend server:** http://127.0.0.1:8000
**Build command:** `bun run build`
**Start command:** `bun run start -- --port 3001`

## Build & Typecheck

| Command | Result |
|---------|--------|
| `bun run typecheck` | PASS |
| `bun run build` | PASS |

Build produced 30 app routes including all dashboard sections and `/auth/sign-in`.

## Route Smoke Test

All routes were visited with an authenticated session. Every route loaded without runtime errors.

| Route | Result | Notes |
|-------|--------|-------|
| `/auth/sign-in` | PASS | Loads sign-in page |
| `/dashboard/overview` | PASS | Dashboard renders |
| `/dashboard/projects` | PASS | Renders cleanly |
| `/dashboard/kanban` | PASS | Renders cleanly |
| `/dashboard/calendar` | PASS | Renders cleanly |
| `/dashboard/chat` | PASS | Renders cleanly |
| `/dashboard/wiki` | PASS | Renders cleanly |
| `/dashboard/files` | PASS | Renders cleanly |
| `/dashboard/notifications` | PASS | Renders cleanly |
| `/dashboard/settings` | PASS | Renders cleanly |

## Console Errors

No JavaScript console errors were observed on any route.

## Failed Requests

The only network failures observed were `net::ERR_ABORTED` / `canceled: true` requests for `/auth/sign-up?_rsc=...`. These are Next.js React Server Component prefetch requests that are cancelled when the middleware redirects an unauthenticated request, and do not affect functionality.

## Screenshots

Key pages captured:

- `w10-5-overview.png`
- `w10-5-chat.png`
- `w10-5-settings.png`

## Summary

All dashboard routes and the sign-in route load successfully in the production build with no console errors. Smoke test PASS.
