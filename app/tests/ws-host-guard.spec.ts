import { expect, test } from '@playwright/test';

import { createWorkspace, registerUser } from './helpers';

const APP = process.env.TEST_APP_URL ?? 'http://localhost:3000';

/**
 * The host-mismatch guard in `src/lib/realtime/use-websocket.ts`.
 *
 * `session_token` is SameSite=Lax and host-scoped, so a page served from
 * `127.0.0.1` whose socket URL names `localhost` authenticates as nobody and
 * every handshake is refused before `accept()` (4401 at the ASGI layer, which the
 * transport flattens into an HTTP 403 for the browser). That reads to a
 * developer as "realtime is broken" with nothing in the console, which is why
 * the hook logs and refuses to connect rather than retrying quietly forever.
 *
 * Asserted as "no socket was opened", not as console text: production builds
 * strip `console.*` (`next.config.ts` `compiler.removeConsole`), so a
 * log-matching spec would pass in dev and assert nothing in CI.
 */
test('a hostname mismatch refuses the socket instead of retrying silently', async ({
  browser
}) => {
  test.setTimeout(180_000);

  const user = await registerUser('guard-owner');
  await createWorkspace(user.token, `guard-${Date.now()}`);

  const mismatched = new URL(APP);
  mismatched.hostname = '127.0.0.1';

  const context = await browser.newContext();
  await context.addCookies([
    {
      name: 'session_token',
      value: user.token,
      domain: '127.0.0.1',
      path: '/',
      httpOnly: true,
      sameSite: 'Lax'
    }
  ]);
  const page = await context.newPage();

  const backendSockets: string[] = [];
  page.on('websocket', (ws) => {
    if (ws.url().includes(':8000')) backendSockets.push(ws.url());
  });

  await page.goto(`${mismatched.toString().replace(/\/$/, '')}/dashboard/chat`);
  await page.setDefaultTimeout(120_000);
  // The page itself must work: the BFF proxies server-side, so an empty list
  // here would mean the test never reached the guard at all.
  await expect(page.getByRole('heading', { name: 'Chat' })).toBeVisible();

  // Give a would-be reconnect every chance to show up before concluding.
  await page.waitForTimeout(6000);
  expect(backendSockets, 'the guard should have refused to connect').toEqual([]);

  await context.close();
});
