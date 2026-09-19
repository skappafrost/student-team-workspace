import { expect, type Browser, type BrowserContext, type Page } from '@playwright/test';

export const APP_URL = process.env.TEST_APP_URL ?? 'http://localhost:3000';

export function url(path: string) {
  return `${APP_URL}${path}`;
}

export interface SeedResult {
  email: string;
  password: string;
  sessionToken: string;
}

/** Register a fresh user through the BFF; returns the httpOnly session token. */
export async function registerUser(): Promise<SeedResult> {
  const email = `e2e_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
  const password = 'password123';
  const res = await fetch(`${APP_URL}/api/auth/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: 'register', email, password })
  });
  if (!res.ok) throw new Error(`register failed: ${res.status} ${await res.text()}`);
  const cookie = res.headers.get('set-cookie') ?? '';
  const match = cookie.match(/session_token=([^;]+)/);
  if (!match) throw new Error('no session_token in register response');
  return { email, password, sessionToken: match[1] };
}

/** Authenticated browser context for a seed user. */
export async function authContext(
  browser: Browser,
  seed: SeedResult
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext();
  await context.addCookies([
    { name: 'session_token', value: seed.sessionToken, domain: 'localhost', path: '/' }
  ]);
  const page = await context.newPage();
  return { context, page };
}

/** Call a BFF route as the seed user. Returns parsed JSON. */
export async function api(
  seed: SeedResult,
  path: string,
  init: { method?: string; body?: unknown } = {}
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Promise<any> {
  const res = await fetch(`${APP_URL}${path}`, {
    method: init.method ?? 'GET',
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${seed.sessionToken}`
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body)
  });
  if (!res.ok) {
    throw new Error(`api ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export interface SeededWorkspace {
  workspaceId: string;
  projectId: string;
  projectName: string;
  channelId: string;
  channelName: string;
}

/**
 * Deterministic seed: workspace → project → channel. All names are unique per
 * run but the SHAPE is fixed, so specs assert structure, not literal strings.
 */
export async function seedWorkspace(seed: SeedResult): Promise<SeededWorkspace> {
  const stamp = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const ws = await api(seed, '/api/workspace', {
    method: 'POST',
    body: { name: `E2E WS ${stamp}`, slug: `e2e-ws-${stamp}` }
  });
  const workspaceId = (ws.workspace?.id ?? ws.workspace?.workspace_id) as string;

  const proj = await api(seed, '/api/projects', {
    method: 'POST',
    body: { name: `E2E Project ${stamp}`, description: 'seeded by e2e' }
  });
  const project = proj.project ?? proj;
  const projectId = (project.id ?? project.project_id) as string;

  const ch = await api(seed, '/api/channels', {
    method: 'POST',
    body: { name: `e2e-chan-${stamp}`, is_private: false }
  });
  const channel = ch.channel ?? ch;
  const channelId = (channel.id ?? channel.channel_id) as string;

  return {
    workspaceId,
    projectId,
    projectName: project.name as string,
    channelId,
    channelName: channel.name as string
  };
}

/** Create a kanban task in a project. */
export async function seedTask(
  seed: SeedResult,
  projectId: string,
  title: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Promise<any> {
  const res = await api(seed, `/api/tasks?project_id=${projectId}`, {
    method: 'POST',
    body: { title, status: 'todo', priority: 'medium' }
  });
  return res.task ?? res;
}

export { expect };
