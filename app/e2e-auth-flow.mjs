/* eslint-disable no-console, unicorn/consistent-function-scoping */
// E2E: register -> login -> dashboard -> logout -> guard (httpOnly cookie flow)
// Run: node e2e-auth-flow.mjs  (needs frontend :3000 + backend :8000 up)
import { chromium } from 'playwright';
import fs from 'node:fs';

const APP = 'http://localhost:3000';
const results = [];
const stamp = Date.now();
const EMAIL = `e2e-${stamp}@example.com`;
const PASSWORD = 'password123';

function step(name, status, detail) {
  results.push({ name, status, detail });
  console.log(`[${status}] ${name} — ${detail}`);
}

const browser = await chromium.launch({ headless: true });
try {
  const ctx = await browser.newContext({ baseURL: APP });
  const page = await ctx.newPage();
  // Give dev server time to compile routes on first visit
  page.setDefaultTimeout(45000);

  async function fillEmail(value) {
    await page.waitForSelector('#email', { state: 'visible', timeout: 10000 });
    await page.type('#email', value, { delay: 10 });
  }

  // ---- 0. Guard: unauthenticated dashboard redirects to sign-in
  await page.goto('/dashboard/overview', { waitUntil: 'domcontentloaded' });
  const u0 = new URL(page.url());
  step(
    'guard-unauth',
    u0.pathname.startsWith('/auth/sign-in') ? 'PASS' : 'FAIL',
    `landed on ${u0.pathname}${u0.search}`
  );

  // ---- 1. Register via UI (auto-login on success)
  await page.goto('/auth/sign-up', { waitUntil: 'domcontentloaded' });
  await fillEmail(EMAIL);
  await page.locator('input[type=password]').first().fill(PASSWORD);
  await page.locator('input[type=password]').nth(1).fill(PASSWORD);
  await Promise.all([
    page.waitForURL(/\/dashboard\/overview/, { timeout: 20000 }),
    page
      .getByRole('button', { name: /sign up/i })
      .first()
      .click()
  ]);
  await page.waitForLoadState('domcontentloaded');
  const dashUrl = new URL(page.url()).pathname;
  step(
    'register-auto-login',
    dashUrl === '/dashboard/overview' ? 'PASS' : 'FAIL',
    `after register at ${dashUrl}`
  );

  // ---- 2. httpOnly cookie present, no token in JS storage
  const cookies = await ctx.cookies(APP);
  const sessionCookie = cookies.find((c) => c.name === 'session_token');
  const cookieOk = sessionCookie && sessionCookie.httpOnly && sessionCookie.path === '/';
  step(
    'cookie-httpOnly',
    cookieOk ? 'PASS' : 'FAIL',
    sessionCookie
      ? `httpOnly=${sessionCookie.httpOnly} sameSite=${sessionCookie.sameSite}`
      : 'no session_token cookie'
  );

  const tokenLeak = await page.evaluate(() => {
    const scan = (store) => Object.keys(store).filter((k) => /token|jwt|access|refresh/i.test(k));
    return [...scan(localStorage), ...scan(sessionStorage)];
  });
  step(
    'no-token-in-js-storage',
    tokenLeak.length === 0 ? 'PASS' : 'FAIL',
    tokenLeak.join(',') || 'clean'
  );

  // ---- 3. Dashboard renders with user menu and shows user's name
  await page.waitForSelector('[aria-label="Account menu"]', { timeout: 10000 });
  await page.click('[aria-label="Account menu"]');
  const userName = await page
    .locator('text=' + EMAIL.split('@')[0])
    .first()
    .innerText()
    .catch(() => '');
  const userEmail = await page
    .locator('text=' + EMAIL)
    .first()
    .innerText()
    .catch(() => '');
  step(
    'dashboard-renders-user',
    userName.length > 0 || userEmail.length > 0 ? 'PASS' : 'FAIL',
    `name: "${userName.slice(0, 40)}" email: "${userEmail.slice(0, 60)}"`
  );

  // ---- 4. Logout via user menu (dropdown already open from step 3)
  await page.getByRole('menuitem', { name: /log out/i }).click();
  await page.waitForURL(/\/auth\/sign-in/, { timeout: 15000 });
  step('logout-redirects', 'PASS', `now at ${new URL(page.url()).pathname}`);

  // ---- 5. Cookie cleared after logout
  const cookiesAfterLogout = await ctx.cookies(APP);
  const stillHasSession = cookiesAfterLogout.some(
    (c) => c.name === 'session_token' && c.value !== ''
  );
  step(
    'cookie-cleared',
    stillHasSession ? 'FAIL' : 'PASS',
    stillHasSession ? 'session_token survived logout' : 'session_token gone'
  );

  // ---- 6. Protected route blocked again
  await page.goto('/dashboard/overview', { waitUntil: 'domcontentloaded' });
  const u6 = new URL(page.url());
  step(
    'guard-after-logout',
    u6.pathname.startsWith('/auth/sign-in') ? 'PASS' : 'FAIL',
    `landed on ${u6.pathname}`
  );

  // ---- 7. Login with wrong password -> visible error
  await page.goto('/auth/sign-in', { waitUntil: 'domcontentloaded' });
  await fillEmail(EMAIL);
  await page.getByLabel(/password/i).fill('wrongpassword');
  await page
    .getByRole('button', { name: /^Sign in$/i })
    .first()
    .click();
  await page.waitForSelector('[role="alert"]', { timeout: 10000 });
  await page.waitForFunction(
    () => (document.querySelector('[role="alert"]')?.textContent ?? '').trim().length > 0,
    undefined,
    { timeout: 5000 }
  );
  const errText = (await page.locator('[role="alert"]').first().innerText()).trim();
  step(
    'login-wrong-pw-error',
    errText.length > 0 ? 'PASS' : 'FAIL',
    `alert: "${errText.slice(0, 80)}"`
  );

  // ---- 8. Register duplicate email -> visible error
  await page.goto('/auth/sign-up', { waitUntil: 'domcontentloaded' });
  await fillEmail(EMAIL);
  await page.locator('input[type=password]').first().fill(PASSWORD);
  await page.locator('input[type=password]').nth(1).fill(PASSWORD);
  await page
    .getByRole('button', { name: /sign up/i })
    .first()
    .click();
  await page.waitForSelector('[role="alert"]', { timeout: 10000 });
  await page.waitForFunction(
    () => (document.querySelector('[role="alert"]')?.textContent ?? '').trim().length > 0,
    undefined,
    { timeout: 5000 }
  );
  const dupText = (await page.locator('[role="alert"]').first().innerText()).trim();
  step(
    'register-duplicate-email-error',
    dupText.length > 0 ? 'PASS' : 'FAIL',
    `alert: "${dupText.slice(0, 80)}"`
  );

  // ---- 9. Login with correct password -> dashboard
  await page.goto('/auth/sign-in', { waitUntil: 'domcontentloaded' });
  await fillEmail(EMAIL);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await Promise.all([
    page.waitForURL(/\/dashboard\/overview/, { timeout: 20000 }),
    page
      .getByRole('button', { name: /^Sign in$/i })
      .first()
      .click()
  ]);
  await page.waitForLoadState('domcontentloaded');
  step(
    'login-success',
    new URL(page.url()).pathname === '/dashboard/overview' ? 'PASS' : 'FAIL',
    `at ${new URL(page.url()).pathname}`
  );
} catch (err) {
  step('unexpected', 'FAIL', String(err).slice(0, 300));
} finally {
  await browser.close();
}

const pass = results.filter((r) => r.status === 'PASS').length;
console.log(`\n===== RESULT: ${pass}/${results.length} passed =====`);
fs.writeFileSync(
  'e2e-auth-result.json',
  JSON.stringify({ when: new Date().toISOString(), pass, total: results.length, results }, null, 2)
);
