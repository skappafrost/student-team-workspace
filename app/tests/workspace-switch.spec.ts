import { expect, test } from '@playwright/test';
import { api, authContext, registerUser, seedWorkspace, url } from './helpers';

test.describe('workspace switcher', () => {
  test('switching workspace updates the sidebar and channel list', async ({ browser }) => {
    const seed = await registerUser();
    await seedWorkspace(seed); // first workspace with one channel
    const stamp = Date.now().toString(36);
    await api(seed, '/api/workspace', {
      method: 'POST',
      body: { name: `Second WS ${stamp}`, slug: `second-ws-${stamp}` }
    });

    const { context, page } = await authContext(browser, seed);
    await page.goto(url('/dashboard/chat'));

    const switcher = page.getByRole('button', { name: 'Switch workspace' });
    await expect(switcher).toBeVisible({ timeout: 15000 });
    // Backend list order is not deterministic — either workspace may be current.
    const initialName = ((await switcher.textContent()) ?? '').trim();

    await switcher.click();
    const options = page.locator('[data-slot="popover-content"] button');
    await expect(options).toHaveCount(2);
    const target = (await options.allTextContents())
      .map((t) => t.trim())
      .find((t) => t !== initialName);
    await options.filter({ hasText: target }).click();

    // Switch triggers a full reload; header now shows the other workspace.
    await expect(switcher).toContainText(target ?? '', { timeout: 15000 });
    if (target?.startsWith('Second WS')) {
      // Second workspace has no channels — empty state renders.
      await expect(page.getByText('No channels found')).toBeVisible({ timeout: 15000 });
    } else {
      await expect(page.getByRole('heading', { name: /e2e-chan-/ })).toBeVisible({
        timeout: 15000
      });
    }

    await context.close();
  });
});
