import { test, expect } from '@playwright/test';
import { registerUser, authContext, seedWorkspace, api } from './helpers';

test('capture workspace switcher', async ({ browser }) => {
  const seed = await registerUser();
  await seedWorkspace(seed);
  const stamp = Date.now().toString(36);
  await api(seed, '/api/workspace', {
    method: 'POST',
    body: { name: `Design Guild ${stamp}`, slug: `design-guild-${stamp}` }
  });

  const { context, page } = await authContext(browser, seed);
  await page.setViewportSize({ width: 1440, height: 900 });

  // Switcher popover open in sidebar
  await page.goto('/dashboard/chat');
  // Expand the icon-collapsed sidebar so the switcher renders at full width
  await page.getByRole('button', { name: 'Toggle Sidebar' }).first().click();
  const switcher = page.getByRole('button', { name: 'Switch workspace' });
  await expect(switcher).toBeVisible({ timeout: 15000 });
  await switcher.click();
  await expect(page.locator('[data-slot="popover-content"] button')).toHaveCount(2);
  await page.waitForTimeout(300); // let the popover entry animation settle
  await page.screenshot({ path: 'qa-evidence/workspace-switcher-dark.png' });

  await context.close();
});
