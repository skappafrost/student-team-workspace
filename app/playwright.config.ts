import { defineConfig } from '@playwright/test';

const APP_URL = process.env.TEST_APP_URL ?? 'http://localhost:3000';
const BACKEND_URL = process.env.STW_BACKEND_URL ?? 'http://localhost:8000';

// The venv layout differs by platform and the specs need a real backend: every
// one of them goes through the BFF at :3000, which proxies to :8000. Without a
// live backend they would only be proving that Next can serve HTML.
const BACKEND_PY = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python';

/**
 * The database the started server must open.
 *
 * Set explicitly rather than inherited, because migrator and server have to be
 * aimed at the same file for the migration to mean anything: with no
 * `DATABASE_URL` the app falls back to `sqlite:///./stw.db`
 * (`backend/config.py:21`) while CI migrates a *different* file
 * (`.github/workflows/ci.yml`, "Prepare backend database"). The server creates no
 * schema of its own, so the specs run against exactly what `alembic upgrade head`
 * built, and the `/readyz` probe below holds the run at 503 until that succeeded.
 *
 * In CI this resolves to the migrated `ci_e2e.db`. On a dev machine it points
 * e2e at its own file instead of writing fixtures into the developer's `stw.db`;
 * override with `DATABASE_URL` to test against a real dev database.
 */
const E2E_DATABASE_URL = process.env.DATABASE_URL ?? 'sqlite:///./ci_e2e.db';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // One worker, everywhere. Measured on a 16 GB machine with 34 specs: four
  // workers crashed the dev server (`RangeError: Array buffer allocation
  // failed`, then `net::ERR_CONNECTION_REFUSED` for every later test, which
  // reads as eleven unrelated failures); two workers lost one spec to its own
  // 120s timeout while webpack compiled routes; one worker was 34/34 green in
  // the *same* wall clock as two, because the bottleneck is the shared dev
  // server, not the CPU. Override with PLAYWRIGHT_WORKERS on a bigger machine.
  workers: Number(process.env.PLAYWRIGHT_WORKERS) || 1,
  reporter: [['html', { open: 'never' }], ['list']],
  // `dev:webpack` compiles a route on its first hit, which on this project's
  // globals.css takes far longer than the 30s default — a cold compile reads to
  // a developer as "the redirect is broken" when nothing is broken.
  timeout: 120_000,
  use: {
    baseURL: APP_URL,
    navigationTimeout: 120_000,
    trace: 'on-first-retry'
  },
  // Playwright owns the process tree here, which a shell `trap` cannot do on
  // Windows: killing the subshell that ran uvicorn left the server listening.
  webServer: [
    {
      // Migrate, then serve, in one `&&`-chained command: Playwright spawns
      // `command` with `shell: true`, so uvicorn only starts after
      // `alembic upgrade head` exits 0, and the `cwd` + `env` below make the
      // chain and the server target the same file. A `globalSetup` migration
      // cannot work here: Playwright sets up `webServer` before it runs
      // `globalSetup`, so the server would already have opened the database.
      // Re-running the chain against a stamped database is a no-op, so CI
      // (which migrates in its own step) pays one extra command and nothing else.
      command: `${BACKEND_PY} -m alembic upgrade head && ${BACKEND_PY} -m uvicorn app:app --port ${new URL(BACKEND_URL).port}`,
      cwd: '../backend',
      env: { ENVIRONMENT: 'dev', DATABASE_URL: E2E_DATABASE_URL },
      // `/readyz`, not `/health`: `/health` touches no table and returns 200 on an
      // empty schema, so "the backend came up" proved nothing about the database.
      // `/readyz` (backend/logging_mw.py) is 200 only when the alembic chain is
      // applied and stamped at the single declared head, and Playwright's probe
      // accepts responses below 404 — so a 503 keeps it waiting rather than waving
      // the run through. `/health` stays documented as the cheap liveness endpoint.
      url: `${BACKEND_URL}/readyz`,
      timeout: 120_000,
      // Something already answering on :8000 (locally) skips this whole
      // `command` — the migration included. The bootstrap this entry proves
      // therefore holds from a cold start only.
      reuseExistingServer: !process.env.CI
    },
    {
      // `--webpack` is mandatory: Turbopack crashes on globals.css on this project.
      command: 'bun run dev:webpack',
      url: APP_URL,
      timeout: 240_000,
      stdout: 'ignore',
      reuseExistingServer: !process.env.CI
    }
  ]
});
