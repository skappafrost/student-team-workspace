import { defineConfig } from '@playwright/test';

const APP_URL = process.env.TEST_APP_URL ?? 'http://localhost:3000';
const BACKEND_URL = process.env.STW_BACKEND_URL ?? 'http://localhost:8000';

// The venv layout differs by platform and the specs need a real backend: every
// one of them goes through the BFF at :3000, which proxies to :8000. Without a
// live backend they would only be proving that Next can serve HTML.
const BACKEND_PY = process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : '.venv/bin/python';

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
      command: `${BACKEND_PY} -m uvicorn app:app --port ${new URL(BACKEND_URL).port}`,
      cwd: '../backend',
      env: { ENVIRONMENT: 'dev' },
      url: `${BACKEND_URL}/health`,
      timeout: 120_000,
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
