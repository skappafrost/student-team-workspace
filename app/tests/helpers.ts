import { request, type Browser, type Page } from '@playwright/test';

export const APP = process.env.TEST_APP_URL ?? 'http://localhost:3000';
export const API = process.env.STW_BACKEND_URL ?? 'http://localhost:8000';
export const PASSWORD = 'password123';

/**
 * Seeding helpers shared by the specs.
 *
 * Fixtures are created through the backend API rather than the BFF because the
 * BFF resolves "the current workspace" as the first row of `/workspaces`, so a
 * spec that needs a second member cannot express it through those routes.
 */

export async function apiPost(
  pathname: string,
  body: unknown,
  token?: string
): Promise<{ status: number; json: any }> {
  const ctx = await request.newContext({
    baseURL: API,
    extraHTTPHeaders: token ? { Authorization: `Bearer ${token}` } : {}
  });
  const res = await ctx.post(pathname, { data: body });
  const json = await res.json().catch(() => null);
  await ctx.dispose();
  return { status: res.status(), json };
}

export async function registerUser(tag: string): Promise<{ email: string; token: string }> {
  const email = `${tag}-${Date.now()}@example.com`;
  const res = await apiPost('/auth/register', { email, password: PASSWORD });
  if (res.status !== 201) {
    throw new Error(`register ${tag} failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  return { email, token: res.json.access_token as string };
}

export async function createWorkspace(token: string, name: string): Promise<string> {
  const res = await apiPost('/workspaces', { name, slug: name, description: 'x' }, token);
  if (res.status !== 201) {
    throw new Error(`workspace failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  return res.json.id as string;
}

/** Create an invite and return its token. */
export async function invite(
  ownerToken: string,
  workspaceId: string,
  email: string,
  role = 'member'
): Promise<string> {
  const res = await apiPost(`/workspaces/${workspaceId}/invites`, { email, role }, ownerToken);
  if (res.status !== 201) {
    throw new Error(`invite failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  return res.json.token as string;
}

export async function acceptInvite(token: string, memberToken: string): Promise<void> {
  const accept = await apiPost('/invites/accept', { token }, memberToken);
  if (accept.status !== 201) {
    throw new Error(`accept failed: ${accept.status} ${JSON.stringify(accept.json)}`);
  }
}

/** Invite `email` and accept it with `memberToken`, ending with a real 2-member workspace. */
export async function inviteAndAccept(
  ownerToken: string,
  workspaceId: string,
  email: string,
  memberToken: string,
  role = 'member'
): Promise<void> {
  const token = await invite(ownerToken, workspaceId, email, role);
  await acceptInvite(token, memberToken);
}

/**
 * A context and page that are already signed in as `token`, NOT yet navigated.
 *
 * Split out from `openPage` because `page.on('websocket')` only reports sockets
 * opened after it is attached — a page that connected during the first load was
 * invisible to the watcher, which is how a healthy connection got measured as
 * zero frames. Attach listeners here, then `page.goto(...)`.
 *
 * The cookie is written for the page's own hostname on purpose: `session_token`
 * is SameSite=Lax and host-scoped, so a page served from `localhost` with a
 * socket aimed at `127.0.0.1` authenticates as nobody.
 */
export async function openAuthContext(
  browser: Browser,
  token: string
): Promise<{ context: import('@playwright/test').BrowserContext; page: Page }> {
  const context = await browser.newContext();
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
  return { context, page };
}

export async function openPage(
  browser: Browser,
  token: string,
  path: string
): Promise<{ context: import('@playwright/test').BrowserContext; page: Page }> {
  const { context, page } = await openAuthContext(browser, token);
  await page.goto(`${APP}${path}`);
  return { context, page };
}
