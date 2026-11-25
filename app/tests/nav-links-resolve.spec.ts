import { expect, test, type Browser } from '@playwright/test';

import { createWorkspace, openPage, registerUser } from './helpers';

const APP = process.env.TEST_APP_URL ?? 'http://localhost:3000';

/**
 * Every nav link must resolve to a real page.
 *
 * `navGroups` in `src/config/nav-config.ts` is the single source for both the
 * sidebar and the command palette, so one entry with no matching route under
 * `src/app/dashboard/` is a 404 that two surfaces serve at once. Nothing else
 * in the repo can see this: `next build` compiles the pages that exist, it does
 * not walk the nav config, and `tsc` never looks at the filesystem.
 *
 * The hrefs are read from the rendered sidebar rather than by importing
 * `nav-config` because a spec that imported the module would be checking the
 * config against itself. The DOM is what the user follows, and it is the same
 * list the palette builds from.
 *
 * Status is asserted on the response, not on 404 markup: `not-found.tsx` lives
 * outside the dashboard segment, so a missing page inside it can render with any
 * local error boundary while the HTTP status is still 404.
 */
test('every sidebar nav link resolves', async ({ browser }: { browser: Browser }) => {
  // One cold `next dev` compile per route, and the list is the whole nav. The
  // default 120s covers maybe six of them, which fails the spec on time, not on
  // a dead link.
  test.setTimeout(420_000);

  const { token } = await registerUser('nav');
  await createWorkspace(token, `nav-${Date.now()}`);
  const { context, page } = await openPage(browser, token, '/dashboard/overview');

  const hrefs: string[] = await page.$$eval('a[href^="/dashboard/"]', (links) => [
    ...new Set(links.map((el) => el.getAttribute('href') as string))
  ]);

  // A gate that found nothing would pass, so the count is part of the assertion.
  expect(hrefs.length, 'sidebar rendered no nav links').toBeGreaterThanOrEqual(8);

  const dead: string[] = [];
  for (const href of hrefs) {
    // domcontentloaded, not load: the chat page opens a websocket, and `load`
    // waits for the connection to settle instead of for the document.
    const res = await page.goto(`${APP}${href}`, { waitUntil: 'domcontentloaded' });
    if (!res || res.status() >= 404) dead.push(`${href} -> ${res?.status() ?? 'no response'}`);
  }

  expect(dead, `nav links that do not resolve:\n${dead.join('\n')}`).toEqual([]);

  await context.close();
});
