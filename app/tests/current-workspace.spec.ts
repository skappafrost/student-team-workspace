import { expect, test } from '@playwright/test';

import { APP, apiSend, bff, createWorkspace, registerUser } from './helpers';

/**
 * `GET /api/workspace/current` is the BFF's answer to "which workspace am I
 * looking at", and it used to give the same one — `{ workspace: null }` at HTTP
 * 200 — for a request with no session, for one the backend refused, and for an
 * account that genuinely belongs to nothing. Only the last of those three is
 * "no workspace", and the difference is not cosmetic: `usePresence` reacts to a
 * null workspace id by switching its query off
 * (`presenceQueryOptions`'s `enabled: !!workspaceId`), so a backend that
 * answered 500 looked like a quiet account and nothing anywhere reported an
 * error.
 *
 * The mapping itself is pinned without a server by
 * `app/tests-unit/current-workspace.test.ts`; what lives here is the part only a
 * live backend can show — that the handler applies it, and that the ordering the
 * `[0]` relies on comes out of the database.
 */

test('a refused workspace lookup is a refusal, not an empty account', async () => {
  test.setTimeout(120_000);

  // A token the backend will not honour: `/workspaces` answers 401, and that
  // status is the whole difference between this line and the old behaviour.
  const refused = await bff('/api/workspace/current', 'not-a-session');
  expect(refused.status).toBe(401);
  expect(refused.body.workspace).toBeUndefined();
  expect(typeof refused.body.error).toBe('string');

  // No cookie at all is its own case, and the sibling `api/presence` already
  // answers it as unauthenticated rather than as an empty list.
  const anonymous = await fetch(`${APP}/api/workspace/current`);
  expect(anonymous.status).toBe(401);
  const anonymousBody = (await anonymous.json()) as { workspace?: unknown };
  expect(anonymousBody.workspace).toBeUndefined();
});

test('an account with no workspace earns 404 "No workspace found"', async () => {
  test.setTimeout(120_000);

  const alone = await registerUser('current-alone');
  const res = await bff('/api/workspace/current', alone.token);
  expect(res.status).toBe(404);
  expect(res.body.error).toBe('No workspace found');
  expect(res.body.workspace).toBeUndefined();
});

test('the current workspace is the backend ordered list, and the same one twice', async () => {
  test.setTimeout(120_000);

  const owner = await registerUser('current-owner');
  const first = await createWorkspace(owner.token, `current-a-${Date.now()}`);
  const second = await createWorkspace(owner.token, `current-b-${Date.now()}`);

  const rows = await apiSend('GET', '/workspaces', { token: owner.token });
  expect(rows.status).toBe(200);
  const current = await bff('/api/workspace/current', owner.token);
  expect(current.status).toBe(200);
  // The BFF takes `[0]` of the backend's answer — which is only a defined
  // position because `GET /workspaces` sorts. Asserting it equals the backend's
  // own first row is the honest version of "the current workspace": *which* of
  // these two rows is first is decided by the `id` tiebreak here, because two
  // POSTs in one second tie on `created_at` by design (SQLite's
  // `(CURRENT_TIMESTAMP)` has second resolution). The `created_at` half is
  // pinned with controlled timestamps in
  // `backend/test_workspace_api.py::test_list_workspaces_orders_by_created_at`.
  expect(current.body.workspace.id).toBe(rows.json[0].id);
  expect([first, second]).toContain(current.body.workspace.id);

  // What the 18 handlers actually depend on: re-resolving per request cannot
  // land on a different workspace. One call is not enough to show the bug.
  const again = await bff('/api/workspace/current', owner.token);
  expect(again.body.workspace.id).toBe(current.body.workspace.id);
});
