import { expect, test } from '@playwright/test';
import { api, authContext, registerUser, seedWorkspace, url, type SeedResult } from './helpers';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';

/** Create a notification directly at the backend for the seed user. */
async function seedNotification(seed: SeedResult, title: string) {
  const me = await api(seed, '/api/auth/me');
  const userId = me.user.id as string;
  const res = await fetch(`${BACKEND_URL}/notifications`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${seed.sessionToken}`
    },
    body: JSON.stringify({ user_id: userId, type: 'message', title, content: 'seeded by e2e' })
  });
  if (!res.ok) throw new Error(`seed notification failed: ${res.status} ${await res.text()}`);
}

test.describe('notifications', () => {
  test('mark all as read clears unread state and persists', async ({ browser }) => {
    const seed = await registerUser();
    await seedWorkspace(seed); // onboarding gate requires a workspace
    await seedNotification(seed, 'First notice');
    await seedNotification(seed, 'Second notice');

    const { context, page } = await authContext(browser, seed);
    await page.goto(url('/dashboard/notifications'));

    await expect(page.getByText('2 unread')).toBeVisible({ timeout: 15000 });
    await page.getByRole('button', { name: 'Mark all as read' }).click();
    await expect(page.getByText('All caught up')).toBeVisible({ timeout: 15000 });

    await page.reload();
    await expect(page.getByText('All caught up')).toBeVisible({ timeout: 15000 });

    await context.close();
  });

  test('empty state renders when there are no notifications', async ({ browser }) => {
    const seed = await registerUser();
    await seedWorkspace(seed);
    const { context, page } = await authContext(browser, seed);
    await page.goto(url('/dashboard/notifications'));

    await expect(page.getByText('You are all caught up')).toBeVisible({ timeout: 15000 });

    await context.close();
  });
});
