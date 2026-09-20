import { expect, test } from '@playwright/test';

import {
  APP,
  apiPost,
  createWorkspace,
  inviteAndAccept,
  openAuthContext,
  registerUser
} from './helpers';

/**
 * "X is typing…" belongs to the channel X typed in.
 *
 * The indicator map and its 3s clear-timers lived in the component, and nothing
 * reset them when the reader switched channel — so the name stayed above the
 * composer of a channel it had nothing to do with until the timer happened to
 * expire. The window is short, which is exactly why it needs a browser to see
 * it: the state is real, and the dismissal is a coincidence of timing.
 */
async function openChat(browser: import('@playwright/test').Browser, token: string, name: string) {
  const { context, page } = await openAuthContext(browser, token);
  page.setDefaultTimeout(120_000);
  await page.goto(`${APP}/dashboard/chat`);
  const row = page.getByText(name, { exact: false }).first();
  await row.waitFor();
  await row.click();
  return { context, page };
}

test('a typer from the channel you left does not follow you to the next one', async ({
  browser
}) => {
  test.setTimeout(240_000);

  const typist = await registerUser('typer');
  const reader = await registerUser('typer-reader');
  const workspaceId = await createWorkspace(typist.token, `ty-${Date.now()}`);
  await inviteAndAccept(typist.token, workspaceId, reader.email, reader.token);
  const alpha = await apiPost(
    `/workspaces/${workspaceId}/channels`,
    { name: `alpha-${Date.now()}`, type: 'general' },
    typist.token
  );
  const beta = await apiPost(
    `/workspaces/${workspaceId}/channels`,
    { name: `beta-${Date.now()}`, type: 'general' },
    typist.token
  );
  expect(alpha.status).toBe(201);
  expect(beta.status).toBe(201);

  const a = await openChat(browser, typist.token, alpha.json.name);
  const b = await openChat(browser, reader.token, alpha.json.name);

  const composer = a.page.getByPlaceholder(`Message #${alpha.json.name}`);
  // Keep typing: the client throttles a send to one per 1.5s, and the reader's
  // indicator only lives 3s, so a single keystroke could expire mid-test.
  await composer.pressSequentially('typing a fairly long message to hold this open', {
    delay: 80
  });

  await expect(b.page.getByText(/typing…/)).toBeVisible({ timeout: 10_000 });

  await b.page.getByText(beta.json.name, { exact: false }).first().click();
  await expect(b.page.getByPlaceholder(`Message #${beta.json.name}`)).toBeVisible();
  // A short, fixed budget is the whole test. `openChat` raises the page default
  // to 120s for webpack's cold compile, and an unbounded `toHaveCount(0)` would
  // happily retry until the leaked 3s timer expired on its own and pass with the
  // fix removed. The point is that the switch itself clears the indicator.
  await expect(b.page.getByText(/typing…/)).toHaveCount(0, { timeout: 500 });

  await a.context.close();
  await b.context.close();
});
