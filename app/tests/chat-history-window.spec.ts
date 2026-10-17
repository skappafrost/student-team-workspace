import { expect, test } from '@playwright/test';

import { bff, createWorkspace, registerUser } from './helpers';

/**
 * The paging params must survive the BFF hop.
 *
 * `api/channels/[channelId]/messages` forwarded only `?q=`, so a client asking for
 * a bounded window silently got the backend default instead — and that default was
 * the 1000 cap applied to the OLDEST end of the channel. The backend now windows
 * from the newest end (covered by `test_chat_api.py`); this covers the layer the
 * browser actually talks to, which is where the parameter was being dropped.
 *
 * Asserted through `bff()` rather than the UI because the "Load earlier"
 * affordance only appears past a full page (50 messages), and the regression
 * guarded here is the passthrough, not the button.
 *
 * Statuses are asserted as `< 300`: the BFF wraps success in its own envelope and
 * answers with NextResponse.json's default 200 while the backend says 201 (same
 * flattening as `api/files`, and out of scope here).
 */
test('the messages BFF passes limit and before through to the backend', async () => {
  const { token } = await registerUser('hist');
  const wsId = await createWorkspace(token, `hist-${Date.now()}`);

  const created = await bff('/api/channels', token, {
    method: 'POST',
    body: { name: 'general', type: 'general', workspace_id: wsId }
  });
  expect(created.status, JSON.stringify(created.body)).toBeLessThan(300);
  const channelId = created.body.channel.id as string;

  for (const content of ['m0', 'm1', 'm2']) {
    const sent = await bff(`/api/channels/${channelId}/messages`, token, {
      method: 'POST',
      body: { content }
    });
    expect(sent.status, JSON.stringify(sent.body)).toBeLessThan(300);
  }

  const window = await bff(`/api/channels/${channelId}/messages?limit=2`, token);
  expect(window.status).toBe(200);
  const contents = (window.body.messages as Array<{ content: string }>).map((m) => m.content);
  // The newest two, oldest-first. A BFF that drops `limit` returns all three.
  expect(contents).toEqual(['m1', 'm2']);

  const older = await bff(
    `/api/channels/${channelId}/messages?limit=2&before=${window.body.messages[0].id}`,
    token
  );
  expect(older.status).toBe(200);
  expect((older.body.messages as Array<{ content: string }>).map((m) => m.content)).toEqual([
    'm0'
  ]);
});
