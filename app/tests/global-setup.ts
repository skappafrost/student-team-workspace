import { spawnSync } from 'node:child_process';
import path from 'node:path';

import { BACKEND_CWD, BACKEND_PY, E2E_DATABASE_URL } from '../playwright.config';

/**
 * Migrate the database the backend `webServer` entry is about to open.
 *
 * Playwright started uvicorn but nothing ran the alembic chain locally, so the
 * schema came from `app.py`'s startup `create_all`: the e2e run could stay green
 * with a migration that dies on its first statement. CI migrates `ci_e2e.db` in
 * its own step, so this is the second run there — applying the chain to a database
 * already at head is a no-op, which is how the two paths end in the same state.
 *
 * Failure here is fatal on purpose: without the schema the backend's readiness
 * probe (`/readyz`, the URL the webServer entry waits on) answers 503 forever, and
 * every spec would then die on a 120s probe timeout blaming a server that never
 * came up.
 */
export default function globalSetup(): void {
  // `tests/` sits directly below the config directory, which is what the
  // webServer entry's relative `cwd` is resolved against.
  const backendDir = path.resolve(__dirname, '..', BACKEND_CWD);
  const python = path.resolve(backendDir, BACKEND_PY);

  const result = spawnSync(python, ['-m', 'alembic', 'upgrade', 'head'], {
    cwd: backendDir,
    env: { ...process.env, DATABASE_URL: E2E_DATABASE_URL },
    encoding: 'utf8'
  });

  if (result.status !== 0) {
    const output = `${result.stdout ?? ''}${result.stderr ?? ''}`.trim();
    throw new Error(
      `alembic upgrade head failed against ${E2E_DATABASE_URL} ` +
        `(exit ${result.status}, spawn error: ${result.error?.message ?? 'none'})\n${output}`
    );
  }
}
