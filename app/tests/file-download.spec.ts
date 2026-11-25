import { expect, test, type Browser } from '@playwright/test';

import { APP, createWorkspace, openAuthContext, registerUser } from './helpers';

/**
 * Downloading a file must return the file.
 *
 * The backend emits `url: "/uploads/{storage_key}"`, which is a path on the
 * backend's origin, and the client fetched it as though it were an app path. Next
 * has no `/uploads` route, so every download — the Files table, a task's
 * attachments, and the link pasted into chat by "Share" — resolved to a 404, and
 * the click handlers passed the rejection into a void `onClick`, so nothing was
 * reported either.
 *
 * Asserted against `/api${file.url}` rather than `file.url`, because the point of
 * the fix is the BFF hop; `file.url` itself is asserted to be unchanged, since the
 * backend's value is pinned by the file API tests and other consumers depend on it.
 *
 * Bytes, not just status: a proxy that answered 200 with a JSON error envelope, or
 * buffered as text, would pass a status-only check and still deliver a broken file.
 */
const PROBE = 'STW-DOWNLOAD-PROBE';

/**
 * Multipart upload through the BFF.
 *
 * `multipart:` rather than `data: new FormData()` — Playwright does not send a
 * FormData passed as `data` with a multipart content type, and Next's
 * `request.formData()` then throws. That is also a real rough edge worth noting:
 * the upload route answers **500**, not 400/415, when the request is not
 * multipart. Out of scope here; this spec only needs to send a valid upload.
 */
async function uploadProbe(page: import('@playwright/test').Page) {
  return page.request.post(`${APP}/api/files`, {
    multipart: {
      file: { name: 'probe.txt', mimeType: 'text/plain', buffer: Buffer.from(PROBE) }
    }
  });
}

test('a workspace file downloads through the BFF', async ({ browser }: { browser: Browser }) => {
  const { token } = await registerUser('dl');
  await createWorkspace(token, `dl-${Date.now()}`);
  const { context, page } = await openAuthContext(browser, token);
  await page.goto(`${APP}/dashboard/files`);

  const uploaded = await uploadProbe(page);
  // `ok()`, not `status() === 201`: the BFF forwards error statuses but answers
  // success with NextResponse.json's default 200 while the backend says 201
  // (api/files/route.ts:108-109). That flattening is a fidelity issue of its own,
  // not what this spec measures, so it is asserted loosely and noted here.
  expect(uploaded.ok(), await uploaded.text()).toBe(true);
  const file = await uploaded.json();
  expect(file.url).toMatch(/^\/uploads\//);

  const download = await page.request.get(`${APP}/api${file.url}`);
  expect(download.status(), await download.text()).toBe(200);
  expect(await download.text()).toBe(PROBE);

  await context.close();
});

test('an anonymous caller cannot download file bytes', async ({ browser }: { browser: Browser }) => {
  const { token } = await registerUser('dl-anon');
  await createWorkspace(token, `dla-${Date.now()}`);
  const { context, page } = await openAuthContext(browser, token);
  await page.goto(`${APP}/dashboard/files`);

  const uploaded = await uploadProbe(page);
  expect(uploaded.ok(), await uploaded.text()).toBe(true);
  const file = await uploaded.json();

  // A fresh context with no cookie: the proxy must not turn into an open static
  // mount, which is exactly what the backend replaced in TA2-2.
  const anon = await (await browser.newContext()).request.get(`${APP}/api${file.url}`);
  expect(anon.status()).toBe(401);

  await context.close();
});
