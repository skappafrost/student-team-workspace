import { test, expect, request, type Browser, type Page } from '@playwright/test';

const APP = process.env.TEST_APP_URL ?? 'http://localhost:3000';
const API = process.env.STW_API_URL ?? 'http://localhost:8000';
const PASSWORD = 'password123';

/**
 * Real-time delivery, measured where the bug lived: the WebSocket protocol.
 *
 * Every browser socket in this app used to die right after a 101 because the
 * server named `Sec-WebSocket-Protocol: stw-ws` when a plain
 * `new WebSocket(url)` had offered nothing, which RFC 6455 §4.1 step 6 makes
 * the client fail on. Nothing in the pytest suite could see it — Starlette's
 * TestClient records the accepted subprotocol without validating it — and uvicorn's
 * `[accepted]` access-log line proves only that the *application* accepted, so
 * the failure looked like a working connection carrying no traffic.
 *
 * Assertions stay at the protocol layer on purpose. `next.config.ts` sets
 * `compiler.removeConsole` for production builds, so a spec that read the
 * client's console would silently assert nothing in CI.
 */

async function backendPost(pathname: string, body: unknown, token?: string) {
  const ctx = await request.newContext({
    baseURL: API,
    extraHTTPHeaders: token ? { Authorization: `Bearer ${token}` } : {}
  });
  const res = await ctx.post(pathname, { data: body });
  const json = await res.json().catch(() => null);
  await ctx.dispose();
  return { status: res.status(), json };
}

/** A two-member workspace with one shared channel, so A's message has a room to reach B in. */
async function seedPair() {
  const stamp = Date.now();
  const emailA = `rt-a-${stamp}@example.com`;
  const emailB = `rt-b-${stamp}@example.com`;
  const a = await backendPost('/auth/register', { email: emailA, password: PASSWORD });
  const b = await backendPost('/auth/register', { email: emailB, password: PASSWORD });
  expect(a.status).toBe(201);
  expect(b.status).toBe(201);
  const tokenA = a.json.access_token as string;
  const tokenB = b.json.access_token as string;

  const ws = await backendPost(
    '/workspaces',
    { name: `RT ${stamp}`, slug: `rt-${stamp}`, description: 'x' },
    tokenA
  );
  expect(ws.status).toBe(201);
  const wsId = ws.json.id as string;

  const invite = await backendPost(
    `/workspaces/${wsId}/invites`,
    { email: emailB, role: 'member' },
    tokenA
  );
  expect(invite.status).toBe(201);
  const accept = await backendPost(
    '/invites/accept',
    { token: invite.json.token },
    tokenB
  );
  expect(accept.status).toBe(201);

  const chan = await backendPost(
    `/workspaces/${wsId}/channels`,
    { name: `room-${stamp}`, type: 'general' },
    tokenA
  );
  expect(chan.status).toBe(201);

  return { tokenA, tokenB, channelName: `room-${stamp}` };
}

/** Watches only the app's own sockets; Next's HMR socket shares the page. */
function watchSockets(page: Page) {
  const opened: string[] = [];
  const errored: string[] = [];
  const frames: string[] = [];
  page.on('websocket', (ws) => {
    if (!ws.url().includes(':8000')) return;
    opened.push(ws.url());
    ws.on('socketerror', (text) => errored.push(text));
    ws.on('framereceived', () => frames.push(ws.url()));
  });
  return { opened, errored, frames };
}

async function openChat(browser: Browser, token: string, channelName: string) {
  const context = await browser.newContext();
  await context.addCookies([
    {
      name: 'session_token',
      value: token,
      domain: new URL(APP).hostname,
      path: '/',
      httpOnly: true,
      sameSite: 'Lax'
    }
  ]);
  const page = await context.newPage();
  const sockets = watchSockets(page);
  // The first hit on a route triggers a webpack compile on a cold cache.
  page.setDefaultTimeout(120_000);
  const channels = page
    .waitForResponse((res) => res.url().includes('/api/channels'), { timeout: 120_000 })
    .then(async (res) => ({
      status: res.status(),
      body: await res.json().catch(() => null)
    }));
  await page.goto(`${APP}/dashboard/chat`);
  const seen = await channels;
  expect(
    seen,
    `the page's own channel list came back as ${seen.status} ${JSON.stringify(seen.body)}`
  ).toMatchObject({ status: 200 });
  const row = page.getByText(channelName, { exact: false }).first();
  await row.waitFor();
  await row.click();
  return { context, page, sockets };
}

test('a browser WebSocket completes its handshake and delivers frames', async ({ browser }) => {
  // A cold `dev:webpack` compile of /dashboard/chat alone can outlast the 30s default.
  test.setTimeout(240_000);
  const { tokenA, tokenB, channelName } = await seedPair();
  const a = await openChat(browser, tokenA, channelName);
  const b = await openChat(browser, tokenB, channelName);

  // One socket per page, not one per render, and both reached the open state:
  // `framereceived` on the author's own socket is the proof, since the channel
  // room broadcast includes the author.
  await expect.poll(() => a.sockets.opened.length).toBe(1);
  await expect.poll(() => b.sockets.opened.length).toBe(1);
  expect(a.sockets.opened[0]).toBe(b.sockets.opened[0]);

  const marker = `rt-${Date.now()}`;
  await a.page.getByPlaceholder(`Message #${channelName}`).fill(marker);
  await a.page.keyboard.press('Enter');

  // The handshake defect: an aborted connection pushes a socketerror here.
  await expect(b.page.getByText(marker, { exact: false }).first()).toBeVisible({
    timeout: 20_000
  });
  expect(a.sockets.errored, a.sockets.errored.join(' | ')).toEqual([]);
  expect(b.sockets.errored, b.sockets.errored.join(' | ')).toEqual([]);
  expect(b.sockets.frames.length, 'peer received no frame at all').toBeGreaterThan(0);

  // The duplicate defect: the room broadcast also reaches the author's socket,
  // and the settle-time refetch carries the same row, so the author must still
  // see exactly one copy.
  await expect(a.page.getByText(marker, { exact: false })).toHaveCount(1);

  // qa-evidence/ is the repo's standing proof that a claim was looked at and
  // not merely asserted, so the delivery run records both pages.
  await b.page.screenshot({
    path: 'qa-evidence/rt-01-peer-received.png',
    fullPage: true
  });
  await a.page.screenshot({
    path: 'qa-evidence/rt-02-sender-single.png',
    fullPage: true
  });

  await a.context.close();
  await b.context.close();
});
