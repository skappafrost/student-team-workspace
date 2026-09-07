// E2E: notifications contract + file-upload trigger
// Assumes backend at :8000 and frontend proxy at :3000 are up.
import { chromium } from 'playwright';
import fs from 'node:fs';

const APP = 'http://localhost:3000';
const API = 'http://127.0.0.1:8000';
const results = [];
const stamp = Date.now();
const EMAIL = `notif-${stamp}@example.com`;
const PASSWORD = 'password123';

function step(name, status, detail) {
  results.push({ name, status: status ? 'PASS' : 'FAIL', detail });
  console.log(`[${status ? 'PASS' : 'FAIL'}] ${name} — ${detail}`);
}

async function api(method, path, body, cookie) {
  const headers = { 'Content-Type': 'application/json' };
  if (cookie) headers.Cookie = `session_token=${cookie}`;
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text().catch(() => '');
  return { status: res.status, text, json: () => (text ? JSON.parse(text) : {}) };
}

const browser = await chromium.launch({ headless: true });
try {
  const ctx = await browser.newContext({ baseURL: APP });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30000);

  // ---- 1. Register user via backend and set cookie in browser context
  const reg = await api('POST', '/auth/register', { email: EMAIL, password: PASSWORD });
  step('register', reg.status === 201, `status=${reg.status}`);
  const regBody = reg.status === 201 ? await reg.json() : {};
  const accessToken = regBody.access_token;
  if (!accessToken) {
    throw new Error('Backend register did not return access_token');
  }

  await ctx.addCookies([
    {
      name: 'session_token',
      value: accessToken,
      domain: 'localhost',
      path: '/',
      httpOnly: true,
      sameSite: 'Lax'
    }
  ]);

  await page.goto('/dashboard/overview', { waitUntil: 'domcontentloaded' });

  // ---- 2. Create workspace via backend using cookie from context
  const cookies = await ctx.cookies(APP);
  const sessionCookie = cookies.find((c) => c.name === 'session_token');
  step('cookie', !!sessionCookie, sessionCookie ? 'session_token present' : 'missing');

  // We need the actual cookie value to call backend directly; use page-level fetch via JS is restricted.
  // Instead create workspace through UI by posting to a route handler not trivial; use backend with cookie string.
  const cookieValue = sessionCookie.value;

  const wsSlug = `ws-${stamp}`;
  const createWs = await api('POST', '/workspaces', { name: 'Test Workspace', slug: wsSlug }, cookieValue);
  step('create-workspace', createWs.status === 201, `status=${createWs.status}`);
  const workspaceId = createWs.status === 201 ? (await createWs.json()).id : null;

  // ---- 3. Upload file via Next.js proxy /api/files (uses same cookie jar in browser)
  await page.goto('/dashboard/files', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /upload file/i }).first().click();
  // Bypass potential file chooser event by setting files directly on the hidden input
  const inputHandle = await page.locator('input[type="file"]').first();
  // Create a small file to upload
  const tmpFile = `C:/Users/Ha Trung/AppData/Local/Temp/notif-test-${stamp}.txt`;
  fs.writeFileSync(tmpFile, `hello ${stamp}`);
  await inputHandle.setInputFiles(tmpFile);
  await page.getByRole('button', { name: /^upload$/i }).first().click();
  // Wait for file to appear in list
  await page.locator(`text=notif-test-${stamp}.txt`).waitFor({ timeout: 20000 });
  step('upload-file', true, `uploaded ${tmpFile}`);

  // ---- 4. Notifications page shows the upload notification
  await page.goto('/dashboard/notifications', { waitUntil: 'domcontentloaded' });
  const notifLocator = page.locator('text=File uploaded');
  await notifLocator.first().waitFor({ timeout: 20000 });
  step('notification-appears', true, 'File uploaded notification visible');

  // ---- 5. Mark as read
  const markReadBtn = page.locator('button[aria-label="Mark as read"]').first();
  await markReadBtn.click();
  // After marking read, the button should disappear (or notification marked)
  await page.locator('text=All caught up').waitFor({ timeout: 20000 });
  step('mark-read', true, 'Notification marked as read');

  // ---- 6. Reload persists
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('text=All caught up').waitFor({ timeout: 20000 });
  step('reload-persists', true, 'Read state persists after reload');

  // ---- 7. Mark-all-read still works (create another notification first)
  // Upload another file to create unread notification, then mark all read
  await page.goto('/dashboard/files', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /upload file/i }).first().click();
  const inputHandle2 = await page.locator('input[type="file"]').first();
  const tmpFile2 = `C:/Users/Ha Trung/AppData/Local/Temp/notif-test-2-${stamp}.txt`;
  fs.writeFileSync(tmpFile2, `hello2 ${stamp}`);
  await inputHandle2.setInputFiles(tmpFile2);
  await page.getByRole('button', { name: /^upload$/i }).first().click();
  await page.locator(`text=notif-test-2-${stamp}.txt`).waitFor({ timeout: 20000 });

  await page.goto('/dashboard/notifications', { waitUntil: 'domcontentloaded' });
  await page.locator('button:has-text("Mark all as read")').first().click();
  await page.locator('text=All caught up').waitFor({ timeout: 20000 });
  step('mark-all-read', true, 'Mark all read works');
} catch (err) {
  step('uncaught-error', false, err.message);
  console.error(err);
} finally {
  await browser.close();
}

const reportPath = `C:/Users/Ha Trung/Documents/Team-workspace/app/e2e-notifications-result.json`;
fs.writeFileSync(reportPath, JSON.stringify({ stamp, results }, null, 2));
console.log(`\nReport: ${reportPath}`);
const failed = results.filter((r) => r.status === 'FAIL');
if (failed.length > 0) {
  console.error('FAILED STEPS:', failed);
  process.exit(1);
}
