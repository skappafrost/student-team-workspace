import { test, expect } from '@playwright/test';
import { registerUser, authContext, seedWorkspace, api } from './helpers';

// 1x1 red PNG
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64'
);

test('capture file preview dialog', async ({ browser }) => {
  const seed = await registerUser();
  const ws = await seedWorkspace(seed);
  const { context, page } = await authContext(browser, seed);
  await page.setViewportSize({ width: 1440, height: 900 });

  // Upload via UI so the record exists with a real storage key
  await page.goto('/dashboard/files');
  await page.getByRole('button', { name: 'Upload file' }).click();
  const chooser = page.waitForEvent('filechooser');
  await page.getByLabel('File drop zone').click();
  (await chooser).setFiles({ name: 'pixel.png', mimeType: 'image/png', buffer: PNG });
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  await expect(page.getByRole('row', { name: /pixel\.png/ })).toBeVisible();

  await page.getByRole('button', { name: 'Preview' }).click();
  await expect(page.getByRole('img', { name: 'Preview of pixel.png' })).toBeVisible();
  await page.screenshot({ path: 'qa-evidence/files-preview-dark.png' });

  // Wiki link surface
  await api(seed, '/api/pages', {
    method: 'POST',
    body: { title: 'Design Notes', slug: 'design-notes', content: 'All decisions.' }
  });
  await api(seed, '/api/pages', {
    method: 'POST',
    body: {
      title: 'Sprint Plan',
      slug: 'sprint-plan',
      content: 'See [[Design Notes]] before estimating.'
    }
  });
  await page.goto('/dashboard/wiki');
  await page.getByText('Sprint Plan').first().click();
  await expect(
    page.locator('article').getByRole('button', { name: 'Design Notes' })
  ).toBeVisible();
  await page.screenshot({ path: 'qa-evidence/wiki-links-dark.png' });

  await context.close();
  void ws;
});
