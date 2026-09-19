import { expect, test } from '@playwright/test';

import { createWorkspace, openPage, registerUser } from './helpers';

/**
 * Workspace settings, driven through a real workspace.
 *
 * This spec used to assert `Demo Admin` / `Jane Member` — rows from the
 * `seededMembers` fixture that `app/src/app/api/workspace/members/route.ts`
 * returns only while the backend is unreachable. Against a live backend with a
 * freshly registered user it could not pass for two independent reasons: the
 * fixture rows are not the data on screen, and a user with zero workspaces is
 * redirected to `/onboarding` by `app/src/app/dashboard/layout.tsx` before the
 * settings page ever renders.
 */
test('owner sees the real member list and can send an invite', async ({ browser }) => {
  test.setTimeout(180_000);

  const owner = await registerUser('ws-owner');
  await createWorkspace(owner.token, `settings-${Date.now()}`);

  const { context, page } = await openPage(browser, owner.token, '/dashboard/settings');

  await expect(page.getByRole('heading', { name: 'Workspace settings' })).toBeVisible();
  // The owner is a member of the workspace they created, so their own row is
  // the one this list must contain. The list arrives after a BFF round trip on a
  // route that may still be compiling, so the 5s expect default is not enough.
  await expect(page.getByText(owner.email)).toBeVisible({ timeout: 30_000 });

  const invited = `invited-${Date.now()}@example.com`;
  await page.getByPlaceholder('colleague@example.com').fill(invited);
  await page.locator("button[type='submit']").first().click();

  await expect(page.getByText('Pending invites')).toBeVisible({ timeout: 30_000 });
  // Scoped to the table row: the address is also in the confirmation toast, so
  // a bare text locator resolves to two elements.
  await expect(page.getByRole('row').filter({ hasText: invited })).toBeVisible();

  await context.close();
});
