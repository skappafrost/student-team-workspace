import { test, expect } from '@playwright/test';
import { registerUser, authContext, seedWorkspace } from './helpers';

test.describe.configure({ mode: 'serial' });

test.describe('chat threads, reactions, edit/delete', () => {
  test('thread panel opens, reply lands in thread', async ({ browser }) => {
    const seed = await registerUser();
    const ws = await seedWorkspace(seed);
    const { context, page } = await authContext(browser, seed);
    await page.goto('/dashboard/chat');

    await page.getByText(ws.channelName).first().click();
    const composer = page.getByPlaceholder(new RegExp(`message #?${ws.channelName}`, 'i'));
    await composer.fill('thread root message');
    await composer.press('Enter');
    const messageList = page.getByLabel('Messages', { exact: true });
    await expect(messageList.getByText('thread root message')).toBeVisible({ timeout: 15000 });

    // Reply via main composer reply flow
    await page
      .getByRole('button', { name: /Reply to/ })
      .first()
      .click();
    await page.getByPlaceholder(/Reply to/).fill('thread reply one');
    await page.getByPlaceholder(/Reply to/).press('Enter');
    await expect(page.getByText(/1 reply/)).toBeVisible({ timeout: 15000 });

    // Open thread panel
    await page.getByRole('button', { name: /open thread/ }).click();
    const panel = page.getByRole('complementary', { name: /Thread started by/ });
    await expect(panel.getByText('thread root message')).toBeVisible();
    await expect(panel.getByText('thread reply one')).toBeVisible();

    // Reply from panel composer
    await panel.getByPlaceholder(/Reply to/).fill('panel reply');
    await panel.getByPlaceholder(/Reply to/).press('Enter');
    await expect(panel.getByText('panel reply')).toBeVisible();

    await panel.getByRole('button', { name: 'Close thread' }).click();
    await expect(panel).not.toBeVisible();

    await context.close();
  });

  test('edit and delete own message', async ({ browser }) => {
    const seed = await registerUser();
    const ws = await seedWorkspace(seed);
    const { context, page } = await authContext(browser, seed);
    await page.goto('/dashboard/chat');

    await page.getByText(ws.channelName).first().click();
    const composer = page.getByPlaceholder(new RegExp(`message #?${ws.channelName}`, 'i'));
    await composer.fill('original content');
    await composer.press('Enter');
    // Scope to the message list: while the send is in flight the composer can
    // still hold the same text, and an unscoped getByText then matches twice.
    const messageList = page.getByLabel('Messages', { exact: true });
    await expect(messageList.getByText('original content')).toBeVisible({ timeout: 15000 });

    // Edit
    await messageList.getByText('original content').hover();
    await page.getByRole('button', { name: /Edit message/ }).click();
    await page.getByLabel('Edit message').fill('edited content');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(messageList.getByText('edited content')).toBeVisible();

    // Delete — guarded by a confirm dialog (review: no delete-without-confirm)
    await messageList.getByText('edited content').hover();
    await page.getByRole('button', { name: /Delete message/ }).click();
    await page.getByRole('button', { name: 'Confirm delete message' }).click();
    await expect(messageList.getByText('edited content')).not.toBeVisible();

    await context.close();
  });
});
