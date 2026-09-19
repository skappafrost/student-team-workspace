import { expect, test, type Browser } from '@playwright/test';

import { createWorkspace, openPage, registerUser } from './helpers';

const APP = process.env.TEST_APP_URL ?? 'http://localhost:3000';

/**
 * Presence dot legibility, measured instead of asserted.
 *
 * Tailwind v4 drops an unregistered utility silently: no build error, the class
 * stays in the DOM, and `background-color` resolves to transparent, so the dot
 * is simply invisible. That is only catchable by looking at computed styles, and
 * it has to be checked per theme because all 11 palettes define their own
 * `--background`, `--destructive` and `--muted-foreground`.
 *
 * The floor is WCAG 1.4.11 (non-text contrast, 3:1), not 1.4.3 (4.5:1 for text):
 * a status dot is a graphical object, and it is never the only carrier — the
 * label is in the `aria-label`/`title` and the picker spells the status out.
 */
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

/** status -> the utility class `PRESENCE_META` maps it to. */
const STATUS_CLASS: Record<string, string> = {
  online: 'bg-presence-online',
  away: 'bg-presence-away',
  dnd: 'bg-presence-dnd',
  offline: 'bg-presence-offline'
};

interface ThemeMeasure {
  theme: string;
  mode: string;
  classes: Record<string, string>;
}

/** WCAG relative luminance, on sRGB bytes already resolved in the browser. */
function luminance([r, g, b]: [number, number, number]): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function ratio(a: [number, number, number], b: [number, number, number]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

let token: string;

test.beforeAll(async () => {
  const owner = await registerUser('dot-owner');
  token = owner.token;
  await createWorkspace(owner.token, `dot-${Date.now()}`);
});

async function measure(browser: Browser, theme: string, mode: string) {
  const { context, page } = await openPage(browser, token, '/dashboard/chat');

  // The presence socket marks this user online on connect, so a real dot is on
  // screen; it is the thing whose visibility is asserted, while the four ratios
  // are measured from fixed classes so the result does not depend on which
  // status the account happens to hold.
  const dot = page.locator('[data-slot="avatar-badge"][data-status]').first();
  await expect(dot).toBeVisible({ timeout: 60_000 });

  // Switching the theme and reading the resolved colors MUST be one synchronous
  // evaluate. Doing it in two steps let the app's own theme provider restore
  // `.dark` between them, so every "light" measurement silently reported the
  // dark palette and the failure looked like a bad color token, not a bad test.
  const result = await page.evaluate((opts: ThemeMeasure) => {
      const el = document.documentElement;
      el.dataset.theme = opts.theme;
      el.classList.toggle('dark', opts.mode === 'dark');

      const canvas = document.createElement('canvas');
      canvas.width = 1;
      canvas.height = 1;
      const ctx = canvas.getContext('2d');
      // `getComputedStyle().backgroundColor` returns the authored form — Chromium
      // does not flatten `oklch()` to `rgb()` — so parsing that string as RGB
      // would read lightness/chroma/hue as color channels and produce confident
      // nonsense. Painting into a canvas always resolves to sRGB.
      const toRgb = (css: string): [number, number, number] => {
        if (!ctx) throw new Error('no 2d context');
        ctx.fillStyle = css;
        ctx.fillRect(0, 0, 1, 1);
        const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
        return [r, g, b];
      };
      const resolve = (cls: string) => {
        const probe = document.createElement('span');
        probe.className = cls;
        document.body.appendChild(probe);
        const value = getComputedStyle(probe).backgroundColor;
        probe.remove();
        return value;
      };

      const pageBg = getComputedStyle(document.body).backgroundColor;
      const badge = document.querySelector<HTMLElement>('[data-slot="avatar-badge"]');
      const badgeColor = badge ? getComputedStyle(badge).backgroundColor : '';
      const statuses: Record<string, string> = {};
      const rgb: Record<string, [number, number, number]> = {
        page: toRgb(pageBg),
        badge: badge ? toRgb(badgeColor) : ([0, 0, 0] as [number, number, number])
      };
      for (const [status, cls] of Object.entries(opts.classes)) {
        statuses[status] = resolve(cls);
        rgb[status] = toRgb(statuses[status]);
      }
      return {
        pageBg,
        badgeColor,
        statuses,
        rgb,
        appliedTheme: el.dataset.theme,
        isDark: el.classList.contains('dark')
      };
    },
    { theme, mode, classes: STATUS_CLASS }
  );
  expect(result.appliedTheme, `theme did not stick: ${theme}`).toBe(theme);
  expect(result.isDark, `${theme}/${mode} measured the wrong mode`).toBe(mode === 'dark');
  await context.close();
  return result;
}

for (const theme of THEMES) {
  for (const mode of ['light', 'dark'] as const) {
    test(`presence colors stay legible in ${theme}/${mode}`, async ({ browser }) => {
      test.setTimeout(120_000);
      const m = await measure(browser, theme, mode);
      // The silent Tailwind failure mode: an unregistered token resolves to
      // transparent, so the dot is invisible whatever the ratio math says.
      expect(m.badgeColor, 'rendered dot resolved to no color').not.toMatch(
        /rgba\(0, 0, 0, 0\)|transparent/
      );
      for (const [status, css] of Object.entries(m.statuses)) {
        expect(css, `${status} emitted no color in ${theme}/${mode}`).not.toMatch(
          /rgba\(0, 0, 0, 0\)|transparent/
        );
        const value = ratio(
          m.rgb[status] as [number, number, number],
          m.rgb.page as [number, number, number]
        );
        // WCAG 1.4.11 (non-text contrast). The dot is never the only carrier:
        // the label is in aria-label/title and the picker spells it out.
        expect(value, `${status} ${css} on ${m.pageBg} in ${theme}/${mode}`).toBeGreaterThanOrEqual(
          3
        );
      }
    });
  }
}

test('every status has a distinct resolved color', async ({ browser }) => {
  test.setTimeout(120_000);
  const m = await measure(browser, 'teamspace', 'dark');
  const values = Object.values(m.statuses);
  expect(new Set(values).size, `statuses collapsed to one color: ${values}`).toBe(4);
});

test('the picker and the dots are recorded for review', async ({ browser }) => {
  test.setTimeout(120_000);
  for (const mode of ['light', 'dark'] as const) {
    // Mode goes in through the app's own storage key rather than by toggling
    // `.dark` after load: the theme provider restores the class on its next
    // render, which produced a "light" screenshot of a dark UI.
    const context = await browser.newContext();
    await context.addInitScript((m) => window.localStorage.setItem('theme', m), mode);
    await context.addCookies([
      {
        name: 'session_token',
        value: token,
        domain: new URL(APP).hostname,
        path: '/',
        httpOnly: true,
        sameSite: 'Lax'
      }
    ]);
    const page = await context.newPage();
    await page.goto(`${APP}/dashboard/chat`);
    expect(
      await page.evaluate(() => document.documentElement.classList.contains('dark')),
      `mode ${mode} did not apply`
    ).toBe(mode === 'dark');

    const dot = page.locator('[data-slot="avatar-badge"][data-status]').first();
    await expect(dot).toBeVisible({ timeout: 60_000 });
    await page.getByRole('button', { name: 'Account menu' }).click();
    await expect(page.getByRole('menuitem', { name: 'Do not disturb' })).toBeVisible();
    await page.screenshot({
      path: `qa-evidence/presence-teamspace-${mode}.png`,
      fullPage: true
    });
    await context.close();
  }
});
