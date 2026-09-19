# Performance budgets

Measured by `tests/perf.spec.ts` (run: `bunx playwright test tests/perf.spec.ts`;
needs backend :8000 + frontend :3000). Report: `qa-evidence/perf/phase6-report.md`.

## Route budgets (dev-server first load, relative)

| Route | JS bytes budget | DOM node budget |
|---|---:|---:|
| /dashboard/chat | ≤ 19 MB | ≤ 1,200 |
| /dashboard/kanban | ≤ 1.8 MB | ≤ 1,200 |
| /dashboard/wiki | ≤ 350 KB | ≤ 1,200 |
| /dashboard/files | ≤ 350 KB | ≤ 1,200 |
| /dashboard/notifications | ≤ 350 KB | ≤ 1,200 |

Budgets are dev-server (unminified webpack) numbers + ~25% headroom. If a
change pushes a route over budget, investigate before shipping — either the
change pulls a new heavy dep into that route's chunk, or a list lost its
windowing.

## Long-list windowing policy

Lists that can grow unbounded MUST window above a threshold:

| List | Threshold | Mechanism |
|---|---:|---|
| Chat message list | 50 root messages | `@tanstack/react-virtual`, dynamic measure |
| File list | 15 files | `@tanstack/react-virtual`, fixed 53px rows, spacer padding |

Below the threshold lists render fully so small views keep simple DOM and
entry animations. New unbounded lists (audit log, activity, wiki pages) must
follow the same pattern when they cross ~50 rows.

## Data-fetching policy

- One key factory per feature (`<entity>Keys`); all consumers of the same
  data share one query key — never inline a second fetcher for the same
  endpoint.
- Cache policy is deliberate per feature; defaults live in
  `src/lib/query-client.ts` (`staleTime: 60s`).
- Realtime surfaces (chat) may use long `staleTime` because updates arrive
  over WebSocket; correctness-sensitive lists (files) use `staleTime: 0`.
