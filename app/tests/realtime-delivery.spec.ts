import { expect, test } from '@playwright/test';

import { apiPost, createWorkspace, inviteAndAccept, openPage, registerUser } from './helpers';

/**
 * Real-time delivery, measured where the bug lived: the WebSocket protocol.
 *
 * Every browser socket in this app used to die right after a 101 because the
 * server named `Sec-WebSocket-Protocol: stw-ws` when a plain
 * `new WebSocket(url)` had offered nothing, which RFC 6455 §4.1 step 6 makes the
 * client fail on. Nothing in the pytest suite could see it — Starlette's
 * TestClient records the accepted subprotocol without validating it — and
 * uvicorn's `[accepted]` access-log line proves only that the *application*
 * accepted, so the failure looked like a working connection carrying no traffic.
 *
 * Assertions stay at the protocol layer on purpose: `next.config.ts` sets
 * `compiler.removeConsole` for production builds, so a spec that read the
 * client's console would silently assert nothing in CI.
 */

/** Watches only the app's own sockets; Next's HMR socket shares the page. */
function watchSockets(page: import('@playwright/test').Page) {
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

async function openChat(browser: import('@playwright/test').Browser, token: string, channelName: string) {
  const { context, page } = await openPage(browser, token, '/dashboard/chat');
  const sockets = watchSockets(page);
  // The first hit on a route triggers a webpack compile on a cold cache.
  page.setDefaultTimeout(120_000);
  const row = page.getByText(channelName, { exact: false }).first();
  await row.waitFor();
  await row.click();
  return { context, page, sockets };
}

test('a browser WebSocket completes its handshake and delivers frames', async ({ browser }) => {
  test.setTimeout(240_000);

  const author = await registerUser('rt-a');
  const peer = await registerUser('rt-b');
  const workspaceId = await createWorkspace(author.token, `rt-${Date.now()}`);
  await inviteAndAccept(author.token, workspaceId, peer.email, peer.token);
  const channel = await apiPost(
    `/workspaces/${workspaceId}/channels`,
    { name: `room-${Date.now()}`, type: 'general' },
    author.token
  );
  expect(channel.status).toBe(201);
  const channelName = channel.json.name as string;

  const a = await openChat(browser, author.token, channelName);
  const b = await openChat(browser, peer.token, channelName);

  // Both pages hold a socket on the same channel room, and neither handshake
  // was aborted. An exact count is not asserted: the hook is designed to
  // reconnect after a close, and under parallel load a reconnect is legitimate
  // client behaviour rather than a defect.
  await expect.poll(() => a.sockets.opened.length).toBeGreaterThan(0);
  await expect.poll(() => b.sockets.opened.length).toBeGreaterThan(0);
  expect(a.sockets.opened[0]).toBe(b.sockets.opened[0]);

  // The reconnect-per-render regression. Not asserted as "no new socket": under
  // parallel load a socket does close, and reconnecting is what the hook is for.
  // The defect being guarded is one socket per render, which 40 keystrokes used
  // to produce, so the bound is generous and still decisive.
  const composer = a.page.getByPlaceholder(`Message #${channelName}`);
  const socketsBeforeTyping = a.sockets.opened.length;
  await composer.pressSequentially('x'.repeat(40));
  await composer.fill('');
  expect(
    a.sockets.opened.length,
    `typing opened ${a.sockets.opened.length - socketsBeforeTyping} sockets in ${socketsBeforeTyping}`
  ).toBeLessThanOrEqual(socketsBeforeTyping + 3);

  const stamp = Date.now();
  const marker = `rt-${stamp}`;
  await composer.fill(marker);
  await a.page.keyboard.press('Enter');

  // The handshake defect: an aborted connection pushes a socketerror here.
  await expect(b.page.getByText(marker, { exact: false }).first()).toBeVisible({
    timeout: 20_000
  });
  expect(a.sockets.errored, a.sockets.errored.join(' | ')).toEqual([]);
  expect(b.sockets.errored, b.sockets.errored.join(' | ')).toEqual([]);

  // The duplicate defect: the room broadcast also reaches the author's socket,
  // and the settle-time refetch carries the same row, so the author must still
  // see exactly one copy.
  await expect(a.page.getByText(marker, { exact: false })).toHaveCount(1);

  // Socket-level proof, asked of the *second* message. Playwright attaches its
  // `framereceived` observer when it surfaces the socket, which can be after the
  // first frame has already landed: a run measured `frames == 0` on a peer that
  // had visibly received the message, while the server logged `delivered=2`. By
  // now the observer is certainly attached, so a zero here is a real absence of
  // frames rather than a race in the measurement.
  const framesBefore = b.sockets.frames.length;
  const second = `rt2-${stamp}`;
  await composer.fill(second);
  await a.page.keyboard.press('Enter');
  await expect(b.page.getByText(second, { exact: false }).first()).toBeVisible({
    timeout: 20_000
  });
  expect(b.sockets.frames.length, 'peer socket carried no frame').toBeGreaterThan(framesBefore);

  // qa-evidence/ is the repo's standing proof that a claim was looked at and
  // not merely asserted, so the delivery run records both pages.
  await b.page.screenshot({ path: 'qa-evidence/rt-01-peer-received.png', fullPage: true });
  await a.page.screenshot({ path: 'qa-evidence/rt-02-sender-single.png', fullPage: true });

  await a.context.close();
  await b.context.close();
});
