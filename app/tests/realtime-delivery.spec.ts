import { expect, test } from '@playwright/test';

import {
  APP,
  apiPost,
  apiSend,
  createWorkspace,
  inviteAndAccept,
  openAuthContext,
  registerUser
} from './helpers';

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

/**
 * Watches the app's own sockets, split by namespace.
 *
 * Two filters matter. Next's HMR socket lives on :3000 and would inflate every
 * count. And since #211 a chat page holds TWO backend sockets — the channel
 * room and the workspace presence room — so filtering on `:8000` alone measures
 * "how many sockets this page has" as one undifferentiated number, which is
 * exactly what made the reconnect question unanswerable.
 */
function watchSockets(page: import('@playwright/test').Page) {
  const channel: string[] = [];
  const presence: string[] = [];
  const errored: string[] = [];
  const frames: string[] = [];
  page.on('websocket', (ws) => {
    if (!ws.url().includes(':8000')) return;
    (ws.url().includes('/ws/workspaces/') ? presence : channel).push(ws.url());
    ws.on('socketerror', (text) => errored.push(text));
    ws.on('framereceived', () => frames.push(ws.url()));
  });
  return { channel, presence, errored, frames };
}

async function openChat(
  browser: import('@playwright/test').Browser,
  token: string,
  channelName: string
) {
  const { context, page } = await openAuthContext(browser, token);
  const sockets = watchSockets(page);
  // The first hit on a route triggers a webpack compile on a cold cache.
  page.setDefaultTimeout(120_000);
  await page.goto(`${APP}/dashboard/chat`);
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

  // One channel socket per page, on the same room, with no aborted handshake.
  // The count is exact now that the watcher is attached before navigation:
  // Playwright only surfaces sockets opened after `page.on('websocket')` was
  // bound, so an earlier version of this spec could not see a socket that
  // connected during first paint and reported a healthy page either way.
  await expect.poll(() => a.sockets.channel.length).toBe(1);
  await expect.poll(() => b.sockets.channel.length).toBe(1);
  expect(a.sockets.channel[0]).toBe(b.sockets.channel[0]);
  // The chat page also holds a presence socket; conflating the two under one
  // `:8000` filter is what made "2→3 sockets" impossible to interpret.
  expect(a.sockets.presence.length).toBeGreaterThanOrEqual(1);

  // The reconnect-per-render regression. Not asserted as "no new socket": under
  // parallel load a socket does close, and reconnecting is what the hook is for.
  // The defect being guarded is one socket per render, which 40 keystrokes used
  // to produce, so the bound is generous and still decisive.
  const composer = a.page.getByPlaceholder(`Message #${channelName}`);
  const socketsBeforeTyping = a.sockets.channel.length;
  await composer.pressSequentially('x'.repeat(40));
  await composer.fill('');
  expect(
    a.sockets.channel.length,
    `typing opened ${a.sockets.channel.length - socketsBeforeTyping} sockets in ${socketsBeforeTyping}`
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

/**
 * Edits and deletes have to reach the room too.
 *
 * `PATCH /messages/{id}` and `DELETE /messages/{id}` used to commit and say
 * nothing — only create and react broadcast — so a peer kept rendering text that
 * had been corrected, and kept rendering a message that had been deleted, until
 * something else refetched the list. The delivery is asserted on both pages: the
 * actor's own tab changes through no mutation of its own (the edit goes over the
 * API, because the UI has no edit affordance yet), so if it updates, the frame is
 * what did it.
 */
test('a corrected message and a deleted one change every open channel view without a reload', async ({
  browser
}) => {
  test.setTimeout(240_000);

  const author = await registerUser('edit-a');
  const peer = await registerUser('edit-b');
  const workspaceId = await createWorkspace(author.token, `edit-${Date.now()}`);
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
  await expect.poll(() => b.sockets.channel.length).toBe(1);

  const stamp = Date.now();
  const original = `edit-${stamp}`;
  await a.page.getByPlaceholder(`Message #${channelName}`).fill(original);
  await a.page.keyboard.press('Enter');
  await expect(b.page.getByText(original, { exact: false }).first()).toBeVisible({
    timeout: 20_000
  });

  const listed = await apiSend('GET', `/channels/${channel.json.id}/messages`, {
    token: author.token
  });
  const target = listed.json.find((m: { content: string }) => m.content === original);
  expect(target, `the posted message is not in the list: ${listed.status}`).toBeTruthy();

  const corrected = `corrected-${stamp}`;
  const edited = await apiSend('PATCH', `/messages/${target.id}`, {
    body: { content: corrected },
    token: author.token
  });
  expect(edited.status).toBe(200);

  for (const [who, page] of [
    ['author', a.page],
    ['peer', b.page]
  ] as const) {
    await expect(page.getByText(corrected, { exact: false }).first(), `on ${who}`).toBeVisible({
      timeout: 20_000
    });
    await expect(
      page.getByText(original, { exact: false }),
      `${who} still shows the old text`
    ).toHaveCount(0);
  }

  const removed = await apiSend('DELETE', `/messages/${target.id}`, { token: author.token });
  expect(removed.status).toBe(204);
  for (const [who, page] of [
    ['author', a.page],
    ['peer', b.page]
  ] as const) {
    await expect(
      page.getByText(corrected, { exact: false }),
      `${who} still shows a deleted row`
    ).toHaveCount(0);
  }

  await a.context.close();
  await b.context.close();
});
