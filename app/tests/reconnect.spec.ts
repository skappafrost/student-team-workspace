import { expect, test } from '@playwright/test';

import {
  APP,
  apiPost,
  createWorkspace,
  inviteAndAccept,
  openAuthContext,
  registerUser
} from './helpers';

/**
 * The outage and the recovery, in one page.
 *
 * While a tab's socket is down the channel list stops being current, and before
 * this test the tab never learned: `useChannelWebSocket` was passed no `onOpen`,
 * the messages query is `staleTime: 60s`, and nothing polls — so a message posted
 * during a network blip stayed invisible in an open chat forever. Presence
 * already refetched on open; chat did not.
 *
 * So the test drives the app's own socket closed and asserts three things about
 * what happens next: the view says so, the reconnect refetches the list, and the
 * message posted while it was down reaches the tab. The navigation counter is
 * what makes the last two mean anything — a reloaded page refetches on its own
 * and would hide a reconnect path that nobody wrote.
 */
async function openChat(browser: import('@playwright/test').Browser, token: string, name: string) {
  const { context, page } = await openAuthContext(browser, token);
  // Record the sockets the app creates so the test can close one. `context
  // .setOffline(true)` was tried first and does not work here: Chromium keeps an
  // established loopback WebSocket running through it, so the page never saw a
  // disconnect at all. Closing the socket produces the same `close` event a real
  // network drop would, and everything after it — the notice, the backoff, the
  // handshake, the refetch — is the app's own code over the real transport.
  await context.addInitScript(() => {
    const win = window as unknown as { __channelSockets: unknown[]; WebSocket: unknown };
    const Real = win.WebSocket as typeof WebSocket & { prototype: object };
    const list: WebSocket[] = [];
    win.__channelSockets = list;
    function Patched(this: WebSocket, url: string | URL, protocols?: string | string[]) {
      const socket = new Real(url as string, protocols);
      if (String(url).includes('/ws/channels/')) list.push(socket);
      return socket;
    }
    Object.setPrototypeOf(Patched, Real);
    Patched.prototype = Real.prototype;
    win.WebSocket = Patched;
  });
  const fetches: string[] = [];
  page.on('request', (req) => {
    if (req.url().includes('/messages')) fetches.push(req.url());
  });
  const navigations: string[] = [];
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame()) navigations.push(frame.url());
  });
  const sockets: string[] = [];
  page.on('websocket', (ws) => {
    if (ws.url().includes('/ws/channels/')) sockets.push(ws.url());
  });
  page.setDefaultTimeout(120_000);
  await page.goto(`${APP}/dashboard/chat`);
  const row = page.getByText(name, { exact: false }).first();
  await row.waitFor();
  await row.click();
  return { context, page, sockets, fetches, navigations };
}

test('a chat tab recovers the gap left by a dropped socket, without being touched', async ({
  browser
}) => {
  test.setTimeout(240_000);

  const author = await registerUser('rc-a');
  const peer = await registerUser('rc-b');
  const workspaceId = await createWorkspace(author.token, `rc-${Date.now()}`);
  await inviteAndAccept(author.token, workspaceId, peer.email, peer.token);
  const channel = await apiPost(
    `/workspaces/${workspaceId}/channels`,
    { name: `room-${Date.now()}`, type: 'general' },
    author.token
  );
  expect(channel.status).toBe(201);
  const name = channel.json.name as string;

  const watcher = await openChat(browser, peer.token, name);

  const stamp = Date.now();
  const warmup = `before-outage-${stamp}`;
  const fetchesAfterLoad = watcher.fetches.length;
  expect(
    (await apiPost(`/channels/${channel.json.id}/messages`, { content: warmup }, author.token))
      .status
  ).toBe(201);
  await expect(watcher.page.getByText(warmup, { exact: false }).first()).toBeVisible({
    timeout: 20_000
  });
  // Why that row is on screen: the list query is 60s fresh, so if no HTTP
  // request went out, the only way it could have arrived is the socket. Counting
  // requests is deterministic where counting received frames is not — Playwright
  // attaches its frame observer after surfacing a socket, so a fast first frame
  // can be missed entirely.
  expect(watcher.fetches.length, 'the page refetched instead of receiving a frame').toBe(
    fetchesAfterLoad
  );

  // Drop the connection and post while it is down. A real network outage cannot
  // be induced reliably here — `context.setOffline(true)` leaves an established
  // loopback WebSocket running, and `page.route(...).abort()` does not keep the
  // reconnect down either — so the test asserts the mechanism rather than the
  // outage: closing the socket must produce a *refetch of the list*, which is
  // what makes the missed message appear. Without the `onOpen` invalidation the
  // fetch count never grows and the test fails, whichever way the text arrives.
  const fetchesBeforeClose = watcher.fetches.length;
  // Dev-mode webpack can reload a page while it is still compiling routes, so
  // the claim is scoped to what the recovery itself does: nothing navigates
  // between the drop and the message appearing.
  const navigationsBeforeClose = watcher.navigations.length;
  const missed = `during-outage-${stamp}`;
  await watcher.page.evaluate(() => {
    const list = (window as unknown as { __channelSockets: WebSocket[] }).__channelSockets;
    list.forEach((socket) => socket.close());
  });
  await expect(watcher.page.getByText('Connection lost — reconnecting…')).toBeVisible({
    timeout: 20_000
  });

  const posted = await apiPost(
    `/channels/${channel.json.id}/messages`,
    { content: missed },
    author.token
  );
  expect(posted.status).toBe(201);

  await expect(watcher.page.getByText(missed, { exact: false }).first()).toBeVisible({
    timeout: 30_000
  });
  expect(watcher.sockets.length, 'the page never reconnected').toBeGreaterThan(1);
  expect(
    watcher.fetches.length,
    `the reconnect did not refetch the list (fetched ${fetchesBeforeClose} times before the drop, ${watcher.fetches.length} after)`
  ).toBeGreaterThan(fetchesBeforeClose);
  expect(
    watcher.navigations.length,
    `the page reloaded ${watcher.navigations.length - navigationsBeforeClose} time(s) during recovery, ` +
      'which would refetch the list on its own and hide the reconnect path'
  ).toBe(navigationsBeforeClose);

  await watcher.context.close();
});
