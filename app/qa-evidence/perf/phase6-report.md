# Phase 6 — Client performance report

Date: 2026-09-15. Branch: feat/notifications-v2. Suite: `tests/perf.spec.ts`
(run: `bunx playwright test tests/perf.spec.ts`, requires backend :8000 +
frontend :3000 running). All numbers from that spec's PERF_* output lines.

## Stage 6.1 — Route budgets (first load, dev server)

| Route | JS bytes | DOM nodes |
|---|---:|---:|
| chat | 15,095,928 | 360 |
| kanban | 1,388,699 | 674 |
| wiki | 139,154 | 676 |
| files | 211,564 | 685 |
| notifications | 71,501 | 668 |

Notes:
- Numbers are from the **webpack dev server** (`bun run dev:webpack`), so JS is
  unminified and inflated vs. production — treat as relative budgets, not
  absolute transfer sizes. Chat is an outlier because the dev chunk graph
  ships the full realtime/composer dependency tree unminified.
- Budgets (dev-server basis, fail-worthy if exceeded by >25% in a rerun):
  chat ≤ 19 MB, kanban ≤ 1.8 MB, wiki/files/notifications ≤ 350 KB;
  DOM nodes ≤ 1,200 per route.

## Stage 6.2 — Long-list windowing (@tanstack/react-virtual)

| List | Threshold | Seeded | Rendered before | Rendered after |
|---|---|---:|---:|---:|
| Message list (`message-list.tsx`) | 50 messages | 120 | **120** | **11** |
| File list (`file-list.tsx`) | 15 files | 20 | **20** | **15** |

- Message list: dynamic-measure virtualizer over root messages; small channels
  (≤50) keep the unwindowed animated list. Scroll stays pinned to the bottom
  when new messages arrive while already near the bottom.
- File list: fixed-height (53px) rows with spacer-row padding inside a
  `max-h-[70vh]` scroll container.
- File seeding is capped at 20 by the backend upload rate limit
  (20/hour per user, `backend/rate_limit.py`), so the file spec uses 20.

## Stage 6.3 — Code-splitting & data-fetching audit

- **Route-level splitting**: Next.js App Router splits per route already;
  heavy deps are route-confined — `recharts` only loads on
  `/dashboard/overview`, `@uiw/react-md-editor` is only a comment reference
  in the wiki viewer (not bundled). No route pulls another feature's heavy
  imports; no changes needed.
- **React Query audit**: one key factory per feature (`notificationKeys`,
  files/kanban equivalents); the notification bell and notifications page
  share `notificationKeys.list()` so a single fetch serves both — no
  duplicate fetchers found. Cache policies are intentional: global
  `staleTime: 60s` (`lib/query-client.ts`), chat messages `staleTime: 5min`
  (realtime updates arrive over WS), files `staleTime: 0` (freshness matters),
  notifications bell polls `refetchInterval: 60s`.
- **BFF handlers**: thin proxies, no per-item fan-out except mark-all-read
  (documented Phase 4 server gap: no bulk endpoint).

## Verification

- `bun run typecheck` clean; `bunx oxlint` clean on touched files.
- Unit: 8/8. Full e2e: 26/27 under parallel load — `theme-integrity`
  intermittently fails only under full parallel workers (pre-existing flake
  shared with `chat-threads`); passes solo in 13.9s. All other 26 pass.
