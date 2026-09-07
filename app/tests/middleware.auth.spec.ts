import { test, expect, type Page } from '@playwright/test';

const APP_URL = process.env.TEST_APP_URL ?? 'http://localhost:3000';

function url(path: string) {
  return `${APP_URL}${path}`;
}

async function createRealSession(_page?: Page) {
  // Register a real user and get a valid session token via the frontend API
  const email = `test${Date.now()}_${Math.random().toString(36).slice(2)}@example.com`;
  const password = 'password123';

  const res = await fetch(`${APP_URL}/api/auth/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: 'register', email, password }),
    credentials: 'include'
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Registration failed: ${res.status} ${errText}`);
  }

  // Get the session_token cookie from the response
  const cookies = res.headers.get('set-cookie');
  const sessionTokenMatch = cookies?.match(/session_token=([^;]+)/);
  const sessionToken = sessionTokenMatch?.[1];

  if (!sessionToken) {
    throw new Error('No session_token in response');
  }

  return { email, password, sessionToken };
}

test.describe('middleware auth route guard', () => {
  test('unauthenticated request to protected route lands on /auth/sign-in with from param', async ({
    browser
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(url('/dashboard/overview'));
    // Middleware adds ?from= query param (URL-encoded)
    await page.waitForURL(url('/auth/sign-in?from=%2Fdashboard%2Foverview'), { timeout: 10000 });
    expect(page.url()).toContain('/auth/sign-in');
    expect(page.url()).toContain('from=');
    await context.close();
  });

  test('authenticated request (with real session_token) to /auth/sign-in lands on /dashboard/overview', async ({
    browser
  }) => {
    // First create a session via the frontend API
    const tempContext = await browser.newContext();
    const tempPage = await tempContext.newPage();
    const { sessionToken } = await createRealSession(tempPage);
    await tempContext.close();

    const context = await browser.newContext();
    const page = await context.newPage();
    await page.context().addCookies([
      {
        name: 'session_token',
        value: sessionToken,
        domain: 'localhost',
        path: '/'
      }
    ]);
    await page.goto(url('/auth/sign-in'));
    // Middleware sees cookie and redirects to dashboard
    await page.waitForURL(url('/dashboard/overview'), { timeout: 15000 });
    expect(page.url()).toBe(url('/dashboard/overview'));
    await context.close();
  });

  test('public route / is accessible without redirect for unauthenticated user', async ({
    browser
  }) => {
    const unauthContext = await browser.newContext();
    const unauthPage = await unauthContext.newPage();
    await unauthPage.goto(url('/'));
    // Unauthenticated user should see landing page (not redirected to sign-in)
    expect(unauthPage.url()).toBe(url('/'));
    await unauthContext.close();
  });

  test('public route / redirects user with real session_token cookie to dashboard', async ({
    browser
  }) => {
    // First create a session via the frontend API
    const tempContext = await browser.newContext();
    const tempPage = await tempContext.newPage();
    const { sessionToken } = await createRealSession(tempPage);
    await tempContext.close();

    const authContext = await browser.newContext();
    const authPage = await authContext.newPage();
    await authPage.context().addCookies([
      {
        name: 'session_token',
        value: sessionToken,
        domain: 'localhost',
        path: '/'
      }
    ]);
    await authPage.goto(url('/'));
    // Landing page server-side validates with backend and redirects authenticated users to dashboard
    await authPage.waitForURL(url('/dashboard/overview'), { timeout: 15000 });
    expect(authPage.url()).toBe(url('/dashboard/overview'));
    await authContext.close();
  });
});
