import { expect, test } from '@playwright/test';

import { API, apiPost, createWorkspace, inviteAndAccept, openPage, registerUser } from './helpers';

/**
 * A notification that only exists as a row is not one the user sees.
 *
 * The push helper used to re-query the rows it had just written with a
 * predicate the fan-out could never satisfy, so it silently returned nothing
 * while every backend test still passed — they all asserted on the row. This
 * asserts the other half: a peer sitting on an unrelated dashboard page, whose
 * only open socket is the presence one, learns about the message without a
 * reload. `staleTime` is 60s and nothing polls, so the socket is the only
 * thing that can move this list.
 */
async function userId(token: string): Promise<string> {
  const res = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const body = await res.json();
  expect(res.status).toBe(200);
  return body.id as string;
}

test('a DM reaches a dashboard tab that has no channel socket open', async ({ browser }) => {
  test.setTimeout(120_000);

  const owner = await registerUser('push-owner');
  const peer = await registerUser('push-peer');
  const workspaceId = await createWorkspace(owner.token, `push-${Date.now()}`);
  await inviteAndAccept(owner.token, workspaceId, peer.email, peer.token);
  const dm = await apiPost(
    `/workspaces/${workspaceId}/dms`,
    { user_id: await userId(peer.token) },
    owner.token
  );
  expect(dm.status).toBe(201);

  const { context, page } = await openPage(browser, peer.token, '/dashboard/notifications');
  // The empty state proves the first fetch already landed, so anything that
  // appears later arrived over the socket rather than with the page load.
  await expect(page.getByText('No notifications')).toBeVisible({ timeout: 30_000 });

  const sent = await apiPost(
    `/channels/${dm.json.id}/messages`,
    { content: 'anything new today?' },
    owner.token
  );
  expect(sent.status).toBe(201);

  await expect(page.getByText('sent you a direct message')).toBeVisible({ timeout: 20_000 });
  await context.close();
});
