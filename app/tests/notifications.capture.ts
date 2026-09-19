import { test, expect } from '@playwright/test';
import { registerUser, authContext, seedWorkspace, api } from './helpers';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000';

test('capture notifications page with unread items', async ({ browser }) => {
  const seed = await registerUser();
  await seedWorkspace(seed);

  // Seed two unread notifications straight at the backend
  const me = await api(seed, '/api/auth/me');
  for (const title of ['Mira mentioned you in #general', 'New file uploaded to Sprint Plan']) {
    await fetch(`${BACKEND_URL}/notifications`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: `session_token=${seed.sessionToken}`
      },
      body: JSON.stringify({ user_id: me.user.id, type: 'mention', title, content: 'Open to view.' })
    });
  }

  const { context, page } = await authContext(browser, seed);
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto('/dashboard/notifications');
  await expect(page.getByText('2 unread')).toBeVisible({ timeout: 15000 });
  await page.screenshot({ path: 'qa-evidence/notifications-unread-dark.png' });

  await context.close();
});
