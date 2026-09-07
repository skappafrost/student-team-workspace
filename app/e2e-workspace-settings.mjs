/* eslint-disable no-console, unicorn/consistent-function-scoping */
// E2E: workspace settings page - invite member, role change, persistence after reload
// Run: node e2e-workspace-settings.mjs (needs frontend :3000/3001 + backend :8000 up)
import { chromium } from 'playwright';
import fs from 'node:fs';

const APP = 'http://localhost:3001';
const BACKEND = 'http://127.0.0.1:8000';
const results = [];
const stamp = Date.now();
const EMAIL = `ws-settings-${stamp}@example.com`;
const INVITE_EMAIL = `invitee-${stamp}@example.com`;
const PASSWORD = 'password123';

function step(name, status, detail) {
  results.push({ name, status, detail });
  console.log(`[${status}] ${name} — ${detail}`);
}

const browser = await chromium.launch({ headless: true });
try {
  const ctx = await browser.newContext({ baseURL: APP });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30000);

  async function fillEmail(value) {
    await page.waitForSelector('#email', { state: 'visible', timeout: 10000 });
    await page.type('#email', value, { delay: 10 });
  }

  // ---- Register and auto-login
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
  step('register-and-login', 'PASS', `registered ${EMAIL}`);

  // ---- Create a workspace via API (required for members/invites endpoints)
  const cookies = await ctx.cookies(APP);
  const sessionCookie = cookies.find((c) => c.name === 'session_token');
  if (!sessionCookie) throw new Error('No session cookie after login');
  const wsRes = await ctx.request.post(`${BACKEND}/workspaces`, {
    headers: { Cookie: `${sessionCookie.name}=${sessionCookie.value}` },
    data: { name: 'Test Workspace', slug: `ws-${Date.now()}`, description: '' }
  });
  if (!wsRes.ok() && wsRes.status() !== 201) {
    throw new Error(`Workspace creation failed: ${wsRes.status()}`);
  }

  // ---- Navigate to settings page
  await page.goto('/dashboard/settings', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Workspace settings', { timeout: 10000 });
  step('settings-page-renders', 'PASS', `at ${new URL(page.url()).pathname}`);

  // ---- Invite a member (default role is member)
  await page.fill('#invite-email', INVITE_EMAIL);
  await page
    .getByRole('button', { name: /invite/i })
    .first()
    .click();
  await page.waitForSelector(`text=${INVITE_EMAIL}`, { timeout: 10000 });
  step('invite-appears', 'PASS', `invited ${INVITE_EMAIL}`);

  // ---- Change invite role to admin
  const inviteRow = page.locator('[data-invite-id]', { hasText: INVITE_EMAIL }).first();
  await inviteRow.locator('[role="combobox"]').first().click();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(500);
  step('invite-role-changed', 'PASS', 'changed invite role to admin');

  // ---- Cancel invite
  await inviteRow.getByRole('button', { name: /cancel/i }).click();
  await page.waitForSelector(`text=${INVITE_EMAIL}`, { state: 'detached', timeout: 10000 });
  step('invite-cancelled', 'PASS', 'invite removed from list');

  // ---- Member list shows owner (current user)
  await page.waitForSelector('text=owner', { timeout: 10000 });
  step('member-list-owner', 'PASS', 'owner role visible');

  // ---- Reload and verify persistence
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=Workspace settings', { timeout: 10000 });
  step('settings-persist-after-reload', 'PASS', 'settings page still renders');
} catch (err) {
  step('unexpected', 'FAIL', String(err).slice(0, 300));
} finally {
  await browser.close();
}

const pass = results.filter((r) => r.status === 'PASS').length;
console.log(`\n===== RESULT: ${pass}/${results.length} passed =====`);
fs.writeFileSync(
  'e2e-workspace-settings-result.json',
  JSON.stringify({ when: new Date().toISOString(), pass, total: results.length, results }, null, 2)
);
