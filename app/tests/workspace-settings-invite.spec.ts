import { test, expect } from '@playwright/test';

const APP_URL = process.env.TEST_APP_URL ?? 'http://localhost:3000';

function url(path: string) {
  return `${APP_URL}${path}`;
}

async function createSession() {
  const email = `ws_test_${Date.now()}_${Math.random().toString(36).slice(2)}@example.com`;
  const res = await fetch(`${APP_URL}/api/auth/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: 'register', email, password: 'password123' }),
    credentials: 'include'
  });
  if (!res.ok) throw new Error(`Registration failed: ${res.status}`);
  const cookies = res.headers.get('set-cookie') ?? '';
  const match = cookies.match(/session_token=([^;]+)/);
  if (!match) throw new Error('No session_token cookie');
  return match[1];
}

test.describe('workspace settings invite flow', () => {
  test('renders members list and can send an invite', async ({ browser }) => {
    const sessionToken = await createSession();

    const context = await browser.newContext();
    const page = await context.newPage();
    await context.addCookies([
      { name: 'session_token', value: sessionToken, domain: 'localhost', path: '/' }
    ]);

    await page.goto(url('/dashboard/settings'));
    await page.waitForSelector('text=Workspace settings', { timeout: 10000 });

    // Members list is rendered with seeded members
    await expect(page.locator('text=Demo Admin')).toBeVisible();
    await expect(page.locator('text=admin@example.com')).toBeVisible();
    await expect(page.locator('text=Jane Member')).toBeVisible();

    // Invite a new member
    const inviteEmail = `invited_${Date.now()}@example.com`;
    await page.fill("input[type='email']", inviteEmail);
    await page.click('button[type="submit"]');

    // Pending invites section appears and contains the new email
    await page.waitForSelector(`text=Pending invites`, { timeout: 5000 });
    await expect(page.locator('text=Pending invites')).toBeVisible();
    const pendingInvite = page.locator('table tbody tr td .font-medium', { hasText: inviteEmail });
    await expect(pendingInvite).toBeVisible();

    await context.close();
  });
});
