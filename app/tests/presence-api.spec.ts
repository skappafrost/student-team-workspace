import { expect, test } from '@playwright/test';

import { bff, createWorkspace, inviteAndAccept, registerUser } from './helpers';

/**
 * The presence BFF, as a contract layer between the browser and the backend.
 *
 * There is no unit runner in this app, so a proxy that silently rewrites status
 * codes is otherwise unverifiable — and the guest rule depends on exactly that:
 * `usePresenceMap` decides whether to draw any dots by checking for a 403. A
 * handler that turned 403 into `[]` would make a guest's UI look like "nobody is
 * online", which is a fabrication, not an absence.
 */
test('presence roster lists members, and a guest is refused rather than answered empty', async () => {
  test.setTimeout(120_000);

  const owner = await registerUser('pres-owner');
  const member = await registerUser('pres-member');
  const guest = await registerUser('pres-guest');
  const workspaceId = await createWorkspace(owner.token, `pres-${Date.now()}`);
  await inviteAndAccept(owner.token, workspaceId, member.email, member.token);
  await inviteAndAccept(owner.token, workspaceId, guest.email, guest.token, 'guest');

  const set = await bff('/api/presence/me', member.token, {
    method: 'POST',
    body: { status: 'dnd', status_message: 'exam week' }
  });
  expect(set.status).toBe(200);
  expect(set.body).toMatchObject({ user_id: expect.any(String), status: 'dnd' });

  const roster = await bff('/api/presence', owner.token);
  expect(roster.status).toBe(200);
  expect(Array.isArray(roster.body)).toBe(true);
  const dndRow = roster.body.find((row: { status: string }) => row.status === 'dnd');
  expect(dndRow, 'the member who set dnd is missing from the roster').toBeTruthy();
  expect(dndRow.status_message).toBe('exam week');
  // The backend answers a bare, unordered array; the BFF must not reshape it.
  expect(roster.body.length).toBeGreaterThanOrEqual(2);

  const asGuest = await bff('/api/presence', guest.token);
  expect(asGuest.status).toBe(403);
  expect(asGuest.body?.error).toContain('Guest');
});
