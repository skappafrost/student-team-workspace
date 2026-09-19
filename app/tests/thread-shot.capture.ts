import { test } from '@playwright/test';
import { registerUser, authContext, seedWorkspace, api } from './helpers';

test('capture thread panel', async ({ browser }) => {
  const seed = await registerUser();
  const ws = await seedWorkspace(seed);
  await api(seed, `/api/channels/${ws.channelId}/messages`, {
    method: 'POST',
    body: { content: 'Standup moved to 10:30 — design review after' }
  });
  const root = await api(seed, `/api/channels/${ws.channelId}/messages`);
  const rootId = (root.messages ?? root)[0].id;
  await api(seed, `/api/channels/${ws.channelId}/messages`, {
    method: 'POST',
    body: { content: 'Can we keep it to 30 minutes?', parent_id: rootId }
  });

  const { context, page } = await authContext(browser, seed);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/dashboard/chat');
  await page.getByText(ws.channelName).first().click();
  await page.getByRole('button', { name: /open thread/ }).click();
  await page
    .getByRole('complementary', { name: /Thread started by/ })
    .getByText('Can we keep it to 30 minutes?')
    .waitFor();
  await page.screenshot({ path: 'qa-evidence/chat-thread-panel-light.png' });
  await context.close();
});
