import { expect, test } from '@playwright/test';

import {
  bff,
  createWorkspace,
  inviteAndAccept,
  openAuthContext,
  registerUser,
  userId
} from './helpers';

/**
 * The keepalive, over the wire, end to end.
 *
 * Two things meet here. The server derives `away` from a stale `last_seen` on a
 * stored `online` row, so a tab nobody is typing in needs a heartbeat or its dot
 * greys out five minutes after the page opened. And until this ran, that
 * heartbeat was the bug: the presence loop seeded `status = "online"` before it
 * looked at the payload, so the keepalive quietly overwrote a `dnd` the user had
 * chosen.
 *
 * So the test asserts both halves at once — the frame is actually sent, and the
 * deliberate status survives it. Either half regressing fails it. The interval is
 * 20s (see `PRESENCE_HEARTBEAT_MS`), which is what lets a spec observe a real
 * tick instead of trusting a constant.
 */
test('the presence keepalive is sent, and does not overwrite a chosen status', async ({
  browser
}) => {
  test.setTimeout(120_000);

  const owner = await registerUser('hb-owner');
  const peer = await registerUser('hb-peer');
  const workspaceId = await createWorkspace(owner.token, `hb-${Date.now()}`);
  await inviteAndAccept(owner.token, workspaceId, peer.email, peer.token);
  const me = await userId(owner.token);

  const { context, page } = await openAuthContext(browser, owner.token);
  const opened: string[] = [];
  const sent: string[] = [];
  page.on('websocket', (ws) => {
    if (!ws.url().includes('/presence')) return;
    opened.push(ws.url());
    ws.on('framesent', (frame) => sent.push(frame.payload.toString()));
  });
  const pings = () => sent.filter((f) => f === '{"type":"ping"}').length;

  await page.goto(`${process.env.TEST_APP_URL ?? 'http://localhost:3000'}/dashboard/chat`);
  // 30s because webpack compiles this route on its first hit.
  await expect
    .poll(() => opened.length, { message: 'presence socket did not open', timeout: 30_000 })
    .toBeGreaterThan(0);

  const chosen = await bff('/api/presence/me', owner.token, {
    method: 'POST',
    body: { status: 'dnd', status_message: 'exam week' }
  });
  expect(chosen.status).toBe(200);

  // The status has to be chosen after the socket opens, or the join's own
  // `online` write would be the thing being tested. The 30s budget is one
  // 20s heartbeat plus slack.
  await expect
    .poll(pings, {
      message: `no heartbeat sent; frames were ${JSON.stringify(sent)}`,
      timeout: 30_000
    })
    .toBeGreaterThan(0);

  const roster = await bff('/api/presence', owner.token);
  expect(roster.status).toBe(200);
  const mine = roster.body.find((row: { user_id: string }) => row.user_id === me);
  expect(mine?.status, 'a heartbeat overwrote the status the user chose').toBe('dnd');
  expect(mine?.status_message, 'a heartbeat cleared the status message').toBe('exam week');

  await context.close();
});
