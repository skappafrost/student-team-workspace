# W5-5 Chat Feature QA Gate Report

**Date:** 2026-08-31
**Tester:** Zen (zen_agent)
**Scope:** Next.js `/dashboard/chat` + FastAPI backend chat channels/messages/WebSocket
**Repo:** `C:\Users\Ha Trung\Documents\Team-workspace\app`
**Backend:** `http://127.0.0.1:8000`
**Frontend dev server:** `http://localhost:3000`
**Commit target:** `W5-5: chat QA gate report`

---

## Summary

| Checklist Item | Result |
|---|---|
| 1. Register/login → open /dashboard/chat → channel list renders | ✅ PASS |
| 2. Create/select channel | ✅ PASS |
| 3. Send 3 messages → appear instantly | ✅ PASS |
| 4. Second browser/incognito → same channel → messages sync | ✅ PASS (after env fix) |
| 5. Reload page → messages persist | ✅ PASS |
| 6. Visual QA: D1/D3/D4/D6/D8 decisions | ⚠️ PARTIAL (see notes) |

**Overall verdict:** Feature is functionally complete and shippable with one configuration caveat (WebSocket domain/cookie mismatch in dev) and one UX polish item (message author_id display).

---

## Build / Type Checks

Run with `NEXT_PUBLIC_API_URL` aligned to the frontend origin during testing; the project code itself passes unchanged.

```bash
bun run typecheck   # PASS
bun run build       # PASS (one pre-existing font fallback warning for Google Sans Flex)
```

- Full `tsc --noEmit` output: no errors.
- `next build` completes successfully.
- Pre-existing warning: `Failed to find font override values for font 'Google Sans Flex' ... Skipping generating a fallback font.` (non-blocking, unrelated to chat).

---

## Functional Test Evidence

A Playwright E2E script seeded a user, workspace, and channel via the FastAPI backend, then:

1. Logged the browser in via `session_token` cookie.
2. Navigated to `/dashboard/chat`.
3. Selected `qa-channel`.
4. Verified seeded messages loaded.
5. Sent three UI messages.
6. Opened a second browser context on the same channel.
7. Sent a message from the second context.
8. Verified the first context received the message via WebSocket broadcast.
9. Reloaded the first context and verified messages persisted.

Result: **all checks passed**. Screenshots are in `qa-evidence/`.

---

## Issues Found

### Issue 1: WebSocket auth fails when `NEXT_PUBLIC_API_URL` uses IP instead of hostname

**Severity:** Medium (dev-only configuration footgun)

**Description:**
The chat page opens its WebSocket directly against `NEXT_PUBLIC_API_URL` (e.g. `ws://127.0.0.1:8000/...`). The backend authenticates the WebSocket using the `session_token` httpOnly cookie. Browsers only send cookies over WebSocket to the same origin as the page. When the frontend runs on `localhost:3000` and `NEXT_PUBLIC_API_URL` is `http://127.0.0.1:8000`, the WebSocket handshake is cross-origin and the cookie is not sent. The backend closes the connection with a 1008 auth error, and the frontend reconnects in a tight loop.

**Evidence:**
- Network trace showed rapid `open/close` cycles for `ws://127.0.0.1:8000/ws/channels/{id}`.
- Backend logs showed `[accepted]` immediately followed by disconnects.
- Direct Python WebSocket test with `?session_token=` query parameter succeeded and received `new_message` broadcasts, proving the backend path works.
- After overriding `NEXT_PUBLIC_API_URL=http://localhost:8000`, the browser sent the cookie and WebSocket sync worked correctly.

**Recommendation:**
- For local development, set `NEXT_PUBLIC_API_URL=http://localhost:8000` (or whatever hostname the app runs on) so the WebSocket is same-origin and the cookie is included.
- Alternatively, have the frontend pass the session token as a query parameter when the WebSocket origin differs, or proxy WebSocket through the Next.js dev server.
- In production, ensure the API domain matches the app domain or use a secure token transport strategy.

### Issue 2: Message bubbles display `author_id` UUID instead of a friendly name

**Severity:** Low (UX polish)

**Description:**
`MessageList` renders `message.author_id` as the sender label. The backend returns a UUID, so every message shows a long hex string rather than a display name. This clutters the UI and looks unfinished.

**Evidence:**
- Screenshot `qa-chat-03-after-send.png` shows `29768e2b-9d77...` above each message.
- Visual analysis flagged the hex strings as noisy and log-like.

**Recommendation:**
- Update the backend `MessageOut` schema or add a `/users/{id}` lookup so the frontend can render a display name.
- Or, at minimum, show only the first name/initials in the message bubble.

---

## Visual QA Notes

DECISIONS.md in the workspace root contains only the "Zero Native Design" rule and the component-base decision (next-shadcn-dashboard-starter, MIT). There is no explicit D1/D3/D4/D6/D8 breakdown in the current files. Visual QA was therefore performed against general craft and the starter reference.

### Strengths
- Modern dark-mode UI consistent with the shadcn/next-shadcn-dashboard-starter reference.
- Clear three-pane layout (global nav, channel list, message feed).
- Good contrast and readable typography.
- Consistent rounded corners and spacing.

### Weaknesses / Polish Items
- **Message author UUID display** (Issue 2) is the most obvious visual regression.
- **No empty-state screenshot** was captured because the seeded test workspace always had a channel. The existing code does show "No messages yet" and "Select a channel" fallbacks.
- **Create channel UI** is not present; channels are created via API or backend only. This matches the current checklist note "Create channel from UI (if implemented) or select existing."

---

## Deliverables

- `w5-qa-report.md` (this file)
- `w5-typecheck.log` and `w5-build.log` (command output)
- `qa-evidence/` screenshots

---

## Commit

To be committed as:

```
W5-5: chat QA gate report
```

with the report, logs, and evidence folder.
