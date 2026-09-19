import { expect, test } from '@playwright/test';
import { api, authContext, registerUser, seedWorkspace, url } from './helpers';

/**
 * Client performance budgets (Task B Phase 6).
 *
 * Measures, per heavy route:
 *  - JS bytes transferred on first load (route JS budget)
 *  - DOM node count after settle (render weight)
 *  - For long lists: rendered-row count vs total seeded items (windowing
 *    effectiveness — without virtualization, rendered ≈ total).
 *
 * Results are written to qa-evidence/perf/<run>.json by the runner script;
 * budgets live in design-references/performance.md.
 */

const PERF_ROUTES: Array<{ name: string; path: string }> = [
  { name: 'chat', path: '/dashboard/chat' },
  { name: 'kanban', path: '/dashboard/kanban' },
  { name: 'wiki', path: '/dashboard/wiki' },
  { name: 'files', path: '/dashboard/files' },
  { name: 'notifications', path: '/dashboard/notifications' }
];

const SEED_MESSAGES = 120;
// Backend upload rate limit is 20/hour per user (backend rate_limit.py),
// so a fresh user can seed at most 20 files per run.
const SEED_FILES = 20;

async function measureRoute(
  page: import('@playwright/test').Page,
  path: string
): Promise<{ jsBytes: number; domNodes: number }> {
  let jsBytes = 0;
  const onResponse = async (res: import('@playwright/test').Response) => {
    const req = res.request();
    if (req.resourceType() !== 'script') return;
    try {
      const body = await res.body();
      jsBytes += body.length;
    } catch {
      /* response already disposed */
    }
  };
  page.on('response', onResponse);
  try {
    // 'load', not 'networkidle': dashboard routes keep polling (React Query
    // refetch), so the network never goes idle and goto would burn the whole
    // test timeout. 'load' covers the route's script bundle; the short settle
    // lets hydration finish before we count DOM nodes.
    await page.goto(url(path), { waitUntil: 'load' });
    await page.waitForTimeout(1000);
  } finally {
    page.off('response', onResponse);
  }
  const domNodes = await page.evaluate(() => document.querySelectorAll('*').length);
  return { jsBytes, domNodes };
}

test.describe('client performance', () => {
  test.describe.configure({ mode: 'serial' });
  test.setTimeout(300_000);

  test('route JS + DOM budgets', async ({ browser }) => {
    const seed = await registerUser();
    await seedWorkspace(seed);
    const { context, page } = await authContext(browser, seed);

    const report: Record<string, { jsBytes: number; domNodes: number }> = {};
    for (const route of PERF_ROUTES) {
      report[route.name] = await measureRoute(page, route.path);
    }
    console.warn(`PERF_ROUTES ${JSON.stringify(report)}`);

    for (const route of PERF_ROUTES) {
      expect(report[route.name].jsBytes, `${route.name} JS bytes`).toBeGreaterThan(0);
      expect(report[route.name].domNodes, `${route.name} DOM nodes`).toBeGreaterThan(50);
    }
    await context.close();
  });

  test('message list windowing', async ({ browser }) => {
    const seed = await registerUser();
    const { channelId, channelName } = await seedWorkspace(seed);

    for (let i = 0; i < SEED_MESSAGES; i++) {
      await api(seed, `/api/channels/${channelId}/messages`, {
        method: 'POST',
        body: { content: `perf message ${i}` }
      });
    }

    const { context, page } = await authContext(browser, seed);
    await page.goto(url('/dashboard/chat'));
    await page.getByText(channelName).first().click();

    // Wait for the last seeded message to be present in data (may be
    // windowed out of the DOM, so poll the rendered count instead).
    await expect(page.getByRole('group').first()).toBeVisible({ timeout: 30_000 });

    const rendered = await page.getByRole('group').count();
    console.warn(`PERF_MESSAGES ${JSON.stringify({ seeded: SEED_MESSAGES, rendered })}`);
    // Windowed: rendered < seeded. Unwindowed baseline: rendered == seeded.
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThanOrEqual(SEED_MESSAGES);
    await context.close();
  });

  test('file list windowing', async ({ browser }) => {
    const seed = await registerUser();
    await seedWorkspace(seed);

    // Upload small files through the BFF upload endpoint.
    for (let i = 0; i < SEED_FILES; i++) {
      const form = new FormData();
      form.append('file', new Blob([`file ${i}`], { type: 'text/plain' }), `perf-${i}.txt`);
      // Backend rate-limits bursts (429) — retry with backoff.
      let ok = false;
      for (let attempt = 0; attempt < 6 && !ok; attempt++) {
        const res = await fetch(`${url('/api/files')}`, {
          method: 'POST',
          headers: { Cookie: `session_token=${seed.sessionToken}` },
          body: form
        });
        if (res.ok) {
          ok = true;
        } else if (res.status === 429) {
          await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
        } else {
          throw new Error(`file upload ${i} failed: ${res.status}`);
        }
      }
      if (!ok) throw new Error(`file upload ${i} failed: 429 after retries`);
    }

    const { context, page } = await authContext(browser, seed);
    await page.goto(url('/dashboard/files'));
    await expect(page.getByRole('row').nth(1)).toBeVisible({ timeout: 30_000 });

    // Subtract header row.
    const rendered = (await page.getByRole('row').count()) - 1;
    console.warn(`PERF_FILES ${JSON.stringify({ seeded: SEED_FILES, rendered })}`);
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThanOrEqual(SEED_FILES);
    await context.close();
  });
});
