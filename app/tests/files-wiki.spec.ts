import { test, expect } from '@playwright/test';
import { registerUser, authContext, seedWorkspace, api } from './helpers';

test.describe.configure({ mode: 'serial' });

// 1x1 transparent PNG
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64'
);

test.describe('files preview + upload states, wiki links', () => {
  test('image preview opens in dialog', async ({ browser }) => {
    const seed = await registerUser();
    await seedWorkspace(seed);
    const { context, page } = await authContext(browser, seed);
    await page.goto('/dashboard/files');

    await page.getByRole('button', { name: 'Upload file' }).click();
    const chooser = page.waitForEvent('filechooser');
    await page.getByLabel('File drop zone').click();
    (await chooser).setFiles({ name: 'pixel.png', mimeType: 'image/png', buffer: PNG });
    await page.getByRole('button', { name: 'Upload', exact: true }).click();

    const row = page.getByRole('row', { name: /pixel\.png/ });
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: 'Preview' }).click();
    await expect(page.getByRole('img', { name: 'Preview of pixel.png' })).toBeVisible();
    await page.keyboard.press('Escape');

    await context.close();
  });

  test('oversized file is rejected client-side', async ({ browser }) => {
    const seed = await registerUser();
    await seedWorkspace(seed);
    const { context, page } = await authContext(browser, seed);
    await page.goto('/dashboard/files');

    await page.getByRole('button', { name: 'Upload file' }).click();
    const chooser = page.waitForEvent('filechooser');
    await page.getByLabel('File drop zone').click();
    (await chooser).setFiles({
      name: 'huge.bin',
      mimeType: 'application/octet-stream',
      buffer: Buffer.alloc(11 * 1024 * 1024)
    });
    await expect(page.getByText(/max 10(\.00)? MB/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Upload', exact: true })).toBeDisabled();

    await context.close();
  });

  test('wiki [[link]] navigates to linked page', async ({ browser }) => {
    const seed = await registerUser();
    await seedWorkspace(seed);

    await api(seed, '/api/pages', {
      method: 'POST',
      body: { title: 'Target Page', slug: 'target-page', content: 'Linked destination.' }
    });
    await api(seed, '/api/pages', {
      method: 'POST',
      body: {
        title: 'Source Page',
        slug: 'source-page',
        content: 'See [[Target Page]] for details.'
      }
    });

    const { context, page } = await authContext(browser, seed);
    await page.goto('/dashboard/wiki');

    await page.getByText('Source Page').first().click();
    const link = page.locator('article').getByRole('button', { name: 'Target Page' });
    await expect(link).toBeVisible();
    await link.click();
    await expect(page.getByText('Linked destination.')).toBeVisible();

    await context.close();
  });
});
