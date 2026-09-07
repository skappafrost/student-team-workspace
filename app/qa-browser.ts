import { chromium, Page } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://localhost:3001';
const API_BASE = 'http://127.0.0.1:8000';

const testEmail = `zen.qa.${Date.now()}@test.com`;
const testPassword = 'TestPass123!';
const testName = 'Zen QA';

async function screenshot(page: Page, name: string) {
  const filePath = `w7-qa-${name}.png`;
  await page.screenshot({ path: filePath, fullPage: false });
  return filePath;
}

async function registerAndSeed() {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: testEmail, password: testPassword, name: testName })
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Backend register failed: ${res.status} ${text}`);
  }
  const data = (await res.json()) as { access_token: string };
  // Create a workspace so /workspaces is non-empty for the proxy logic
  const slug = `qa-${Date.now()}`;
  await fetch(`${API_BASE}/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${data.access_token}` },
    body: JSON.stringify({ name: 'QA Workspace', slug })
  });
  return data.access_token;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();

  const accessToken = await registerAndSeed();
  await context.addCookies([
    {
      name: 'session_token',
      value: accessToken,
      domain: 'localhost',
      path: '/',
      httpOnly: true,
      secure: false,
      sameSite: 'Lax'
    }
  ]);

  // 1. Files page - empty state
  await page.goto(`${BASE}/dashboard/files`);
  await page.waitForSelector('text=Upload and manage workspace files', { timeout: 10000 });
  await screenshot(page, '01-files-empty');

  // 2. Upload file via dialog
  await page.click('button:has-text("Upload file")');
  await page.waitForSelector('text=Choose a file or drag it into the drop zone below', { timeout: 10000 });
  const testFile = 'qa-test-upload.txt';
  fs.writeFileSync(testFile, `QA upload test at ${new Date().toISOString()}`);
  const input = await page.$('input[type="file"]');
  if (!input) throw new Error('File input not found');
  await input.setInputFiles(path.resolve(testFile));
  const uploadButton = await page.$('div[data-slot="dialog-footer"] button:has-text("Upload")');
  if (!uploadButton) throw new Error('Upload button not found');
  await uploadButton.click();
  // Wait for list to update
  await page.waitForTimeout(3000);
  await screenshot(page, '02-files-uploaded');

  // 3. Notifications page - should show upload notification
  await page.goto(`${BASE}/dashboard/notifications`);
  await page.waitForSelector('text=View and manage all your notifications', { timeout: 10000 });
  await screenshot(page, '03-notifications');

  // 4. Mark notification read if possible
  const markReadBtn = await page.$('button:has-text("Mark as read")');
  if (markReadBtn) {
    await markReadBtn.click();
    await page.waitForTimeout(2000);
    await screenshot(page, '04-notifications-read');
  }

  // 5. Reload and verify persistence
  await page.reload();
  await page.waitForSelector('text=View and manage all your notifications', { timeout: 10000 });
  await screenshot(page, '05-notifications-reload');

  await browser.close();
  console.log('QA browser run complete');
})();
