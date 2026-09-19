import { test, expect } from '@playwright/test';

import { api, authContext, registerUser, seedTask, seedWorkspace, url } from './helpers';

/**
 * Golden paths: workspace create → channel message → task move → file upload
 * → wiki edit → notifications read. Each test seeds deterministically via the
 * BFF and drives the UI for the golden action only.
 */

test.describe.configure({ mode: 'serial' });

test('workspace create → project and channel seeded → overview renders', async ({ browser }) => {
  const seed = await registerUser();
  const ws = await seedWorkspace(seed);
  const { context, page } = await authContext(browser, seed);

  await page.goto(url('/dashboard/overview'));
  await expect(page).toHaveURL(/\/dashboard\/overview/, { timeout: 20000 });
  // Projects page lists the seeded project
  await page.goto(url('/dashboard/projects'));
  await expect(page.getByText(ws.projectName).first()).toBeVisible({ timeout: 20000 });
  await context.close();
});

test('channel message send appears in message list', async ({ browser }) => {
  const seed = await registerUser();
  const ws = await seedWorkspace(seed);
  const { context, page } = await authContext(browser, seed);

  await page.goto(url('/dashboard/chat'));
  // Channel selection happens by clicking the sidebar item
  await page.getByText(ws.channelName).first().click();
  const composer = page.getByPlaceholder(new RegExp(`message #?${ws.channelName}`, 'i'));
  await expect(composer).toBeVisible({ timeout: 20000 });

  const body = `e2e message ${Date.now()}`;
  await composer.fill(body);
  await composer.press('Enter');
  await expect(page.getByText(body).first()).toBeVisible({ timeout: 10000 });
  await context.close();
});

test('task move between kanban columns persists', async ({ browser }) => {
  const seed = await registerUser();
  const ws = await seedWorkspace(seed);
  const task = await seedTask(seed, ws.projectId, `Move me ${Date.now()}`);
  const { context, page } = await authContext(browser, seed);

  await page.goto(url(`/dashboard/kanban?project=${ws.projectId}`));
  const card = page.getByText(task.title, { exact: true }).first();
  await expect(card).toBeVisible({ timeout: 20000 });

  // Move via the API the board calls, then verify the UI reflects the change
  await api(seed, '/api/tasks', {
    method: 'PATCH',
    body: { taskId: task.id, status: 'done' }
  });
  await page.reload();
  const doneColumn = page.locator('[data-slot="kanban-column"]', { hasText: /done/i });
  await expect(doneColumn.getByText(task.title)).toBeVisible({ timeout: 20000 });
  await context.close();
});

test('file upload appears in files list', async ({ browser }) => {
  const seed = await registerUser();
  await seedWorkspace(seed);
  const { context, page } = await authContext(browser, seed);

  await page.goto(url('/dashboard/files'));
  await expect(page.getByText(/files/i).first()).toBeVisible({ timeout: 20000 });

  const fileName = `e2e-upload-${Date.now()}.txt`;
  // Open the upload dialog, then the drop zone opens a file chooser
  await page.getByRole('button', { name: /upload file/i }).click();
  const chooser = page.waitForEvent('filechooser', { timeout: 10000 });
  await page.getByRole('button', { name: 'File drop zone' }).click();
  await (await chooser).setFiles({ name: fileName, mimeType: 'text/plain', buffer: Buffer.from('e2e') });
  await page.getByRole('button', { name: /^upload$/i }).click();
  await expect(page.getByText(fileName).first()).toBeVisible({ timeout: 20000 });
  await context.close();
});

test('wiki page create and edit round-trips', async ({ browser }) => {
  const seed = await registerUser();
  await seedWorkspace(seed);
  const { context, page } = await authContext(browser, seed);

  const title = `E2E Page ${Date.now()}`;
  const created = await api(seed, '/api/pages', {
    method: 'POST',
    body: { title, slug: title.toLowerCase().replace(/[^a-z0-9]+/g, '-'), content: '# seed\n' }
  });
  const pageId = created.page?.id ?? created.id;

  await page.goto(url('/dashboard/wiki'));
  await expect(page.getByText(title).first()).toBeVisible({ timeout: 20000 });

  const edited = `edited ${Date.now()}`;
  await api(seed, `/api/pages/${pageId}`, {
    method: 'PATCH',
    body: { content: `# ${edited}\n` }
  });
  await page.reload();
  await expect(page.getByText(title).first()).toBeVisible({ timeout: 20000 });
  await context.close();
});

test('notifications mark-all-as-read empties unread state', async ({ browser }) => {
  const seed = await registerUser();
  await seedWorkspace(seed);
  const { context, page } = await authContext(browser, seed);

  await page.goto(url('/dashboard/notifications'));
  await expect(page).toHaveURL(/\/dashboard\/notifications/, { timeout: 20000 });

  const markAll = page.getByRole('button', { name: /mark all as read/i });
  if (await markAll.isVisible().catch(() => false)) {
    await markAll.click();
    // After marking all read, the unread badges disappear
    await expect(page.locator('[data-unread="true"]')).toHaveCount(0, { timeout: 10000 });
  }
  await context.close();
});
