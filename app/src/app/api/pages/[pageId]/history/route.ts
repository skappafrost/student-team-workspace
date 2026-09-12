import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

async function backendRequest(
  path: string,
  init: RequestInit,
  sessionCookie: string
): Promise<Response> {
  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`
    },
    cache: 'no-store'
  });
}

async function resolveWorkspaceId(sessionCookie: string): Promise<string | null> {
  const res = await backendRequest('/workspaces', { method: 'GET' }, sessionCookie);
  if (!res.ok) return null;
  const workspaces = (await res.json()) as Array<{ id: string }>;
  return workspaces[0]?.id ?? null;
}

/** GET /api/pages/[pageId]/history — list versions, newest first. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pageId: string }> }
) {
  const { pageId } = await params;
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const workspaceId = await resolveWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace' }, { status: 404 });
  }
  const res = await backendRequest(
    `/workspaces/${workspaceId}/pages/${encodeURIComponent(pageId)}/history`,
    { method: 'GET' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to load history');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  return NextResponse.json({ versions: await res.json() });
}

/** POST /api/pages/[pageId]/history { version } — restore a version. */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ pageId: string }> }
) {
  const { pageId } = await params;
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const workspaceId = await resolveWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace' }, { status: 404 });
  }
  const body = (await request.json().catch(() => ({}))) as { version?: number };
  if (typeof body.version !== 'number') {
    return NextResponse.json({ error: 'version required' }, { status: 400 });
  }
  const res = await backendRequest(
    `/workspaces/${workspaceId}/pages/${encodeURIComponent(pageId)}/restore/${body.version}`,
    { method: 'POST' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to restore version');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  return NextResponse.json({ page: await res.json() });
}
