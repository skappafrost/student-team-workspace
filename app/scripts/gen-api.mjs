#!/usr/bin/env node
/**
 * Generate TypeScript types from the backend OpenAPI schema.
 *
 * Run: bun run gen:api   (from the app/ directory)
 *
 * What it does:
 *  1. Spins up the backend (uvicorn) on 127.0.0.1:8123 with a TEMPORARY
 *     SQLite DB (DATABASE_URL pointing at the OS temp dir) — never the
 *     dev stw.db, never Postgres.
 *  2. GETs /openapi.json from that throwaway server.
 *  3. Runs openapi-typescript to emit src/types/api.d.ts with a
 *     DO-NOT-EDIT-GENERATED header.
 *  4. Kills the server and deletes the temp DB files.
 *
 * Env overrides:
 *  STW_VENV_PYTHON  Python interpreter with uvicorn+fastapi installed
 *                   (default: main checkout backend/.venv on this machine).
 *  GEN_API_PORT     Port for the throwaway server (default 8123).
 */

import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const APP_DIR = resolve(here, '..');
const BACKEND_DIR = resolve(APP_DIR, '..', 'backend');
const OUT_FILE = join(APP_DIR, 'src', 'types', 'api.d.ts');

const PORT = process.env.GEN_API_PORT ?? '8123';
const VENV_PYTHON =
  process.env.STW_VENV_PYTHON ??
  'C:/Users/Ha Trung/Documents/Team-workspace/stw/backend/.venv/Scripts/python.exe';

const HEADER = `/**
 * DO-NOT-EDIT-GENERATED
 *
 * Generated from the backend OpenAPI schema via \`bun run gen:api\`
 * (openapi-typescript). Do not edit by hand — regenerate instead.
 */
`;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForOpenApi(url, timeoutMs = 60000) {
  const start = Date.now();
  for (;;) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.text();
    } catch {
      // Server not up yet — keep polling.
    }
    if (Date.now() - start > timeoutMs) {
      throw new Error(`timed out waiting for ${url}`);
    }
    await sleep(500);
  }
}

async function main() {
  const workDir = mkdtempSync(join(tmpdir(), 'stw-gen-api-'));
  const dbPath = join(workDir, 'gen-api.db').replace(/\\/g, '/');
  const uploadDir = join(workDir, 'uploads');

  const server = spawn(
    VENV_PYTHON,
    ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', String(PORT)],
    {
      cwd: BACKEND_DIR,
      env: {
        ...process.env,
        DATABASE_URL: `sqlite:///${dbPath}`,
        UPLOAD_DIR: uploadDir,
        JWT_SECRET_KEY: 'gen-api-throwaway-secret'
      },
      stdio: 'ignore'
    }
  );

  const kill = () => {
    if (server.exitCode === null) {
      if (process.platform === 'win32') {
        spawnSync('taskkill', ['/pid', String(server.pid), '/T', '/F'], { stdio: 'ignore' });
      } else {
        server.kill('SIGTERM');
      }
    }
  };
  process.on('exit', kill);
  process.on('SIGINT', () => {
    kill();
    process.exit(130);
  });

  try {
    const url = `http://127.0.0.1:${PORT}/openapi.json`;
    console.log(`[gen:api] waiting for ${url} ...`);
    const schemaText = await waitForOpenApi(url);
    const schemaFile = join(workDir, 'openapi.json');
    writeFileSync(schemaFile, schemaText);

    console.log('[gen:api] running openapi-typescript ...');
    const gen = spawnSync(
      'bun',
      ['x', 'openapi-typescript', schemaFile, '-o', OUT_FILE],
      { cwd: APP_DIR, stdio: 'inherit' }
    );
    if (gen.status !== 0) {
      throw new Error('openapi-typescript failed');
    }

    const body = readFileSync(OUT_FILE, 'utf8');
    if (!body.startsWith('DO-NOT-EDIT-GENERATED') && !body.includes('DO-NOT-EDIT-GENERATED')) {
      writeFileSync(OUT_FILE, `${HEADER}\n${body}`);
    }
    console.log(`[gen:api] wrote ${OUT_FILE}`);
  } finally {
    kill();
    await sleep(1000);
    rmSync(workDir, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(`[gen:api] FAILED: ${err.message}`);
  process.exit(1);
});
