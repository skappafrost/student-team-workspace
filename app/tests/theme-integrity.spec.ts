import { expect, test } from '@playwright/test';
import { authContext, registerUser, seedWorkspace, url } from './helpers';

const THEMES = [
  'teamspace',
  'claude',
  'discord',
  'supabase',
  'vercel',
  'mono',
  'notebook',
  'light-green',
  'zen',
  'astro-vista',
  'whatsapp'
];

// Serial: the test below already opens 11 browser contexts in a loop; letting
// it share workers with other files under fullyParallel starved the dev server
// and raced the background assertion. (Review: Vex, PR #137.)
test.describe.configure({ mode: 'serial' });

test.describe('theme integrity', () => {
  test('all 11 themes apply in dark mode with distinct backgrounds and no missing surfaces', async ({
    browser
  }) => {
    const seed = await registerUser();
    await seedWorkspace(seed);

    const seen = new Set<string>();
    for (const theme of THEMES) {
      // Fresh context per theme: the client provider mirrors state into
      // cookies/localStorage, so reusing one context races the next theme.
      const { context, page } = await authContext(browser, seed);
      await context.addCookies([
        { name: 'theme', value: 'dark', domain: 'localhost', path: '/' },
        { name: 'active_theme', value: theme, domain: 'localhost', path: '/' }
      ]);
      await page.goto(url('/dashboard'));

      // Theme attribute lands on <html>
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme, {
        timeout: 15000
      });

      // Background token resolves to a real color, and differs per theme.
      // Poll: under load the computed style can still show the default
      // theme's background right after data-theme lands, so wait until the
      // read is both real and (for later themes) not a stale repeat.
      let bg = '';
      await expect(async () => {
        bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
        expect(bg).not.toBe('rgba(0, 0, 0, 0)');
        expect(seen.has(bg)).toBe(false);
      }).toPass({ timeout: 15000 });
      seen.add(bg);

      // Core surfaces render: sidebar nav + header
      await expect(page.getByRole('link', { name: 'Overview' }).first()).toBeVisible({
        timeout: 15000
      });
      await context.close();
    }
    expect(seen.size).toBe(THEMES.length);
  });
});
