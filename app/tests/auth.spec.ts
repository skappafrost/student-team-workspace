import { test, expect } from '@playwright/test';

import { api, APP_URL, registerUser, url } from './helpers';

/**
 * Golden path: auth. Converts the standalone e2e-auth-flow.mjs script into
 * Playwright specs (register → cookie → dashboard → logout → guards → errors).
 */
test.describe('auth golden path', () => {
  test('register → auto-login → dashboard → logout → guards', async ({ page }) => {
    const email = `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
    const password = 'password123';

    // Guard: unauthenticated dashboard redirects to sign-in
    await page.goto(url('/dashboard/overview'));
    await page.waitForURL(/\/auth\/sign-in/, { timeout: 15000 });
    expect(page.url()).toContain('from=');

    // Register via UI (auto-login on success)
    await page.goto(url('/auth/sign-up'));
    await page.locator('#email').fill(email);
    await page.locator('input[type=password]').first().fill(password);
    await page.locator('input[type=password]').nth(1).fill(password);
    await Promise.all([
      page.waitForURL(/\/(dashboard\/overview|onboarding)/, { timeout: 30000 }),
      page.getByRole('button', { name: /sign up/i }).first().click()
    ]);

    // httpOnly session cookie, no token in JS storage
    const cookies = await page.context().cookies(APP_URL);
    const session = cookies.find((c) => c.name === 'session_token');
    expect(session?.httpOnly).toBe(true);
    const tokenLeak = await page.evaluate(() => {
      const scan = (store: Storage) =>
        Object.keys(store).filter((k) => /token|jwt|access|refresh/i.test(k));
      return [...scan(localStorage), ...scan(sessionStorage)];
    });
    expect(tokenLeak).toEqual([]);

    // Fresh users land on onboarding (no workspace yet); seed one via the BFF
    // so the dashboard renders with the account menu.
    const token = session!.value;
    await api({ sessionToken: token } as never, '/api/workspace', {
      method: 'POST',
      body: { name: `Auth WS ${Date.now()}`, slug: `auth-ws-${Date.now()}` }
    });
    await page.goto(url('/dashboard/overview'));
    await page.waitForURL(/\/dashboard\/overview/, { timeout: 20000 });

    // Logout via account menu
    await page.click('[aria-label="Account menu"]');
    await page.getByRole('menuitem', { name: /log out/i }).click();
    await page.waitForURL(/\/auth\/sign-in/, { timeout: 15000 });

    // Cookie cleared; protected route blocked again
    const after = await page.context().cookies(APP_URL);
    expect(after.some((c) => c.name === 'session_token' && c.value !== '')).toBe(false);
    await page.goto(url('/dashboard/overview'));
    await page.waitForURL(/\/auth\/sign-in/, { timeout: 15000 });
  });

  test('wrong password shows inline error', async ({ page }) => {
    const seed = await registerUser();
    await page.goto(url('/auth/sign-in'));
    await page.locator('#email').fill(seed.email);
    await page.getByLabel(/password/i).fill('wrongpassword1');
    await page.getByRole('button', { name: /^Sign in$/i }).first().click();
    const alert = page.locator('[role="alert"]').first();
    await expect(alert).toBeVisible({ timeout: 10000 });
    await expect(alert).not.toBeEmpty();
  });

  test('duplicate registration shows inline error', async ({ page }) => {
    const seed = await registerUser();
    await page.goto(url('/auth/sign-up'));
    await page.locator('#email').fill(seed.email);
    await page.locator('input[type=password]').first().fill(seed.password);
    await page.locator('input[type=password]').nth(1).fill(seed.password);
    await page.getByRole('button', { name: /sign up/i }).first().click();
    const alert = page.locator('[role="alert"]').first();
    await expect(alert).toBeVisible({ timeout: 10000 });
    await expect(alert).not.toBeEmpty();
  });

  test('sign in with correct password lands on dashboard', async ({ page }) => {
    const seed = await registerUser();
    await page.goto(url('/auth/sign-in'));
    await page.locator('#email').fill(seed.email);
    await page.getByLabel(/password/i).fill(seed.password);
    await Promise.all([
      page.waitForURL(/\/(dashboard\/overview|onboarding)/, { timeout: 30000 }),
      page.getByRole('button', { name: /^Sign in$/i }).first().click()
    ]);
  });
});
