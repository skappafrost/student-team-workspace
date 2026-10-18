import { expect, test } from '@playwright/test';

import {
  APP,
  apiPost,
  bff,
  createWorkspace,
  invite,
  inviteAndAccept,
  openPage,
  registerUser,
  userId
} from './helpers';

/**
 * The handlers here used to answer real requests from arrays written into the
 * source: `features/workspace/fixture.ts` held a roster and an invite list that
 * `PATCH`/`POST`/`DELETE` mutated in place (so one visitor's write changed what
 * the next one read), `api/pages` carried a five-page wiki tree it returned for a
 * missing session, a missing workspace, and — checked ahead of `!res.ok` — a 404,
 * and the notification store began every visitor with the same five invented rows.
 *
 * `playwright.config.ts` starts a live backend for every run, so these assertions
 * are made against rows the backend wrote. Each test checks both halves: the data
 * is the backend's, and a refusal arrives as a refusal rather than as a plausible
 * 200.
 */

/** Rows from the deleted workspace fixture — ids included, since a real row is a uuid. */
const INVENTED_ROSTER = [
  'Alice Nguyen',
  'Bob Tran',
  'Carol Le',
  'David Pham',
  'alice@example.com',
  'bob@example.com',
  'usr_1',
  'usr_2'
];

/** The row from the deleted `seededInvites`. */
const INVENTED_INVITE = 'pending.member@example.com';

/** Titles from the deleted `MOCK_PAGES` tree. */
const INVENTED_PAGES = [
  'Getting Started',
  'Engineering',
  'Frontend',
  'Backend',
  'React Guidelines'
];

/** Titles from the deleted `mockNotifications`, kept to the three no backend writes. */
const INVENTED_NOTIFICATIONS = [
  'New team member joined',
  'New product added',
  'Billing cycle updated'
];

// `bff()` and `apiPost()` answer `any`; every shape is named here instead, so a
// handler that starts returning something else fails on the shape, not silently.
type MemberRow = { user?: { email?: string } };
type InviteRow = { email?: string };
type PageRow = { title?: string };
type NotificationRow = { content?: string | null; read?: boolean };

const memberEmails = (body: unknown): (string | undefined)[] =>
  ((body as { members?: MemberRow[] }).members ?? []).map((m) => m.user?.email);

const inviteEmails = (body: unknown): (string | undefined)[] =>
  ((body as { invites?: InviteRow[] }).invites ?? []).map((i) => i.email);

const pageTitles = (body: unknown): (string | undefined)[] =>
  ((body as { pages?: PageRow[] }).pages ?? []).map((p) => p.title);

const inboxRows = (body: unknown): NotificationRow[] =>
  (body as { notifications?: NotificationRow[] }).notifications ?? [];

test('the roster and the invite list are the backend rows, and a cookie-less write cannot rewrite them', async ({
  browser
}) => {
  test.setTimeout(180_000);

  const owner = await registerUser('noinvent-owner');
  const peer = await registerUser('noinvent-peer');
  const workspaceId = await createWorkspace(owner.token, `noinvent-${Date.now()}`);
  await inviteAndAccept(owner.token, workspaceId, peer.email, peer.token);
  const invitedAddress = `pending-${Date.now()}@example.com`;
  await invite(owner.token, workspaceId, invitedAddress);

  const members = await bff('/api/workspace/members', owner.token);
  expect(members.status).toBe(200);
  expect(memberEmails(members.body)).toContain(owner.email);
  expect(memberEmails(members.body)).toContain(peer.email);
  for (const invented of INVENTED_ROSTER) {
    expect(JSON.stringify(members.body)).not.toContain(invented);
  }

  const invites = await bff('/api/workspace/invites', owner.token);
  expect(invites.status).toBe(200);
  expect(inviteEmails(invites.body)).toContain(invitedAddress);
  expect(JSON.stringify(invites.body)).not.toContain(INVENTED_INVITE);

  // The branch these rows used to come from accepted writes: a request with no
  // session rewrote the module-scope arrays and returned them, and the splice was
  // unrecoverable. Refusing the request is only half the fix, so the reads after
  // it are asserted too.
  //
  // `bff()` always sets the cookie header, so 'not-a-session' reaches the handler
  // as a session that exists — its 401 check passes and the request lands in the
  // no-workspace 404 instead. A write has to arrive with no session at all, and
  // only a context that never had a cookie added sends that (the anonymous shape
  // `file-download.spec.ts` uses).
  const anonymous = await browser.newContext();

  const tamperedMember = await anonymous.request.fetch(`${APP}/api/workspace/members`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    data: { memberId: 'usr_2', role: 'admin' }
  });
  expect(tamperedMember.status(), await tamperedMember.text()).toBe(401);
  expect(((await tamperedMember.json()) as { members?: unknown }).members).toBeUndefined();

  const tamperedInvite = await anonymous.request.fetch(
    `${APP}/api/workspace/invites?inviteId=inv_1`,
    { method: 'DELETE' }
  );
  expect(tamperedInvite.status(), await tamperedInvite.text()).toBe(401);
  expect(((await tamperedInvite.json()) as { invites?: unknown }).invites).toBeUndefined();

  await anonymous.close();

  const membersAfter = await bff('/api/workspace/members', owner.token);
  expect(memberEmails(membersAfter.body)).toEqual(memberEmails(members.body));
  const invitesAfter = await bff('/api/workspace/invites', owner.token);
  expect(inviteEmails(invitesAfter.body)).toContain(invitedAddress);

  // src/proxy.ts only matches /dashboard and /auth, so an anonymous request does
  // reach the handler; it is answered as unauthenticated, not as somebody's team.
  // A bare `fetch` from the test process carries no cookie of its own.
  const rosterWithoutSession = await fetch(`${APP}/api/workspace/members`);
  expect(rosterWithoutSession.status).toBe(401);
  expect(((await rosterWithoutSession.json()) as { members?: unknown }).members).toBeUndefined();

  // A freshly registered account owns no workspace. This used to be the same
  // fabricated roster, because the fallback keyed on "no rows", not on "the
  // backend refused". The cookie here is real, so this is the 404 branch on
  // purpose — the one the two writes above could not reach.
  const alone = await registerUser('noinvent-alone');
  const noWorkspace = await bff('/api/workspace/members', alone.token);
  expect(noWorkspace.status).toBe(404);
  expect(noWorkspace.body.members).toBeUndefined();
});

test('a page list the backend refused is an error, not a fabricated tree', async () => {
  test.setTimeout(180_000);

  // No cookie anywhere: a bare `fetch` builds its headers from scratch, so this
  // answers the handler's own 401, not the no-workspace 404 a `bff()` call with a
  // bogus token falls into.
  const anonymous = await fetch(`${APP}/api/pages`);
  expect(anonymous.status).toBe(401);
  expect(((await anonymous.json()) as { pages?: unknown }).pages).toBeUndefined();

  // A token the backend will not honour. `bff()` sends it as a cookie, so the
  // handler passes its 401 check and lands in the 404 branch: `/workspaces`
  // answers 401, so there is no workspace whose pages could be listed. This used
  // to answer five hand-written pages while a 500 on the same route reported the
  // failure honestly. A backend nobody can reach is the 503 branch, which these
  // specs cannot produce — `playwright.config.ts` starts one that answers.
  const noWorkspace = await bff('/api/pages', 'not-a-session');
  expect(noWorkspace.status).toBe(404);
  expect(noWorkspace.body.pages).toBeUndefined();
  expect(typeof noWorkspace.body.error).toBe('string');

  const owner = await registerUser('noinvent-pages');
  await createWorkspace(owner.token, `noinvent-pages-${Date.now()}`);

  const before = await bff('/api/pages', owner.token);
  expect(before.status).toBe(200);
  expect(before.body.pages).toEqual([]);

  const created = await bff('/api/pages', owner.token, {
    method: 'POST',
    body: {
      title: 'Real Page',
      slug: `real-page-${Date.now()}`,
      content: 'a row the backend wrote'
    }
  });
  expect(created.status).toBe(201);

  const after = await bff('/api/pages', owner.token);
  expect(pageTitles(after.body)).toEqual(['Real Page']);
  for (const invented of INVENTED_PAGES) {
    expect(JSON.stringify(after.body)).not.toContain(invented);
  }
});

test('the header bell lists the inbox GET /api/notifications returns', async ({ browser }) => {
  test.setTimeout(180_000);

  const owner = await registerUser('bell-owner');
  const peer = await registerUser('bell-peer');
  const workspaceId = await createWorkspace(owner.token, `bell-${Date.now()}`);
  await inviteAndAccept(owner.token, workspaceId, peer.email, peer.token);

  // The row the bell must draw: a DM message writes a notification for the peer.
  const dm = await apiPost(
    `/workspaces/${workspaceId}/dms`,
    { user_id: await userId(peer.token) },
    owner.token
  );
  expect(dm.status).toBe(201);
  const sent = await apiPost(
    `/channels/${dm.json.id}/messages`,
    { content: 'anything new today?' },
    owner.token
  );
  expect(sent.status).toBe(201);

  const inbox = await bff('/api/notifications', peer.token);
  expect(inbox.status).toBe(200);
  const rows = inboxRows(inbox.body);
  expect(rows.some((r) => r.content?.includes('sent you a direct message'))).toBe(true);
  const unread = rows.filter((r) => r.read !== true).length;

  // /dashboard/overview and not /dashboard/notifications: that page draws the
  // same rows in its own list, and a text locator there could not tell the two.
  const { context, page } = await openPage(browser, peer.token, '/dashboard/overview');
  await page.getByRole('button', { name: /notifications/i }).click();

  await expect(page.getByText('sent you a direct message')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(`${unread} new`)).toBeVisible();
  for (const invented of INVENTED_NOTIFICATIONS) {
    await expect(page.getByText(invented)).toHaveCount(0);
  }

  await context.close();
});
