import { test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

import { api, authContext, registerUser, url } from './helpers';

/**
 * QA evidence pipeline (Task B 1.3): captures one screenshot per dashboard
 * surface in both themes into qa-evidence/ as `ui-<surface>-<theme>.png`.
 * See qa-evidence/README.md for the naming policy.
 *
 * Run: bun run qa:evidence   (needs frontend :3000 + backend :8000 up)
 */

const OUT_DIR = path.join(__dirname, '..', 'qa-evidence');

const SURFACES = [
  ['overview', '/dashboard/overview'],
  ['projects', '/dashboard/projects'],
  ['kanban', '/dashboard/kanban'],
  ['calendar', '/dashboard/calendar'],
  ['deadlines', '/dashboard/deadlines'],
  ['chat', '/dashboard/chat'],
  ['files', '/dashboard/files'],
  ['wiki', '/dashboard/wiki'],
  ['notifications', '/dashboard/notifications'],
  ['settings', '/dashboard/settings']
] as const;

test('capture dashboard surfaces in both themes', async ({ browser }) => {
  test.setTimeout(300000);

  const seed = await registerUser();
  const stamp = Date.now().toString(36);
  await api(seed, '/api/workspace', {
    method: 'POST',
    body: { name: `QA WS ${stamp}`, slug: `qa-ws-${stamp}` }
  });

  fs.mkdirSync(OUT_DIR, { recursive: true });

  for (const theme of ['light', 'dark'] as const) {
    const { context, page } = await authContext(browser, seed);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((t) => localStorage.setItem('theme', t), theme);

    for (const [area, route] of SURFACES) {
      await page.goto(url(route), { waitUntil: 'domcontentloaded' });
      // Let client-side data settle before capturing
      await page.waitForTimeout(2000);
      await page.screenshot({ path: path.join(OUT_DIR, `ui-${area}-${theme}.png`) });
    }
    await context.close();
  }
});
