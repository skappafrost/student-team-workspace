import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { WorkspaceRole } from '@/features/workspace/types';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

/** `404` is the caller's finding, `503` the BFF's own; see `getCurrentWorkspace`. */
type WorkspaceLookup =
  | { ok: true; workspaceId: string }
  | { ok: false; status: 404 | 503; error: string };

/**
 * The workspace a session acts on is the first row `/workspaces` shares with it.
 * A backend that cannot be reached is not the same finding as one that answers
 * with no rows: left uncaught, the rejection escapes the handler and Next answers
 * its generic 500, which carries no `{error}` body for a client to render.
 */
async function getCurrentWorkspace(sessionCookie: string): Promise<WorkspaceLookup> {
  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  }).catch(() => null);
  if (!res) return { ok: false, status: 503, error: 'Backend unreachable' };
  if (!res.ok) return { ok: false, status: 404, error: 'No workspace found' };
  const data = (await res.json().catch(() => null)) as Array<{ id: string }> | null;
  if (!Array.isArray(data) || data.length === 0) {
    return { ok: false, status: 404, error: 'No workspace found' };
  }
  return { ok: true, workspaceId: data[0].id };
}

async function backendRequest(
  path: string,
  init: RequestInit,
  sessionCookie: string
): Promise<Response> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`,
      ...(init.headers as Record<string, string>)
    },
    cache: 'no-store'
  }).catch(() => null);
  // Every handler here already turns a non-2xx into a status plus an `{error}`,
  // so a refusal and a failure to connect get the same honest shape.
  return res ?? new Response('Backend unreachable', { status: 503 });
}

/**
 * `GET` is the roster, `PATCH` one role change, and the backend is the only
 * source for both. Nothing here is reachable without a session, and a refusal is
 * forwarded with its own status: the two handlers used to answer a missing cookie
 * or an unreachable backend from a module-scope array that `PATCH` also wrote
 * into, so one visitor's role change showed up in the next reader's list.
 */
export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const workspace = await getCurrentWorkspace(sessionCookie);
  if (!workspace.ok) {
    return NextResponse.json({ error: workspace.error }, { status: workspace.status });
  }
  const res = await backendRequest(
    `/workspaces/${workspace.workspaceId}/members`,
    { method: 'GET' },
    sessionCookie
  );
  if (!res.ok) {
    return NextResponse.json({ error: 'Failed to fetch members' }, { status: res.status });
  }
  const members = (await res.json()) as Array<Record<string, unknown>>;
  return NextResponse.json({ members });
}

export async function PATCH(request: Request) {
  const sessionCookie = await getSessionCookie();
  const body = (await request.json().catch(() => ({}))) as {
    memberId?: string;
    role?: WorkspaceRole;
  };
  if (!body.memberId || !body.role) {
    return NextResponse.json({ error: 'memberId and role are required' }, { status: 400 });
  }
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const workspace = await getCurrentWorkspace(sessionCookie);
  if (!workspace.ok) {
    return NextResponse.json({ error: workspace.error }, { status: workspace.status });
  }
  const res = await backendRequest(
    `/workspaces/${workspace.workspaceId}/members/${encodeURIComponent(body.memberId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ role: body.role })
    },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to update member role');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const listRes = await backendRequest(
    `/workspaces/${workspace.workspaceId}/members`,
    { method: 'GET' },
    sessionCookie
  );
  const members = listRes.ok ? ((await listRes.json()) as Array<Record<string, unknown>>) : [];
  return NextResponse.json({ members });
}
