import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { WikiPageSummary } from '@/features/wiki/api/types';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

async function getCurrentWorkspaceId(sessionCookie: string): Promise<string | null> {
  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  if (!res.ok) return null;
  const data = (await res.json()) as Array<{ id: string }>;
  if (!Array.isArray(data) || data.length === 0) return null;
  return data[0].id;
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
      Cookie: `session_token=${sessionCookie}`,
      ...(init.headers as Record<string, string>)
    },
    cache: 'no-store'
  });
}

/**
 * `GET` is the page list, `POST` one new page.
 *
 * A refusal from the backend is forwarded with its own status. `GET` used to
 * answer three of them — no session, no workspace, and 404 in particular — with a
 * hand-written page tree, so a workspace that does not exist rendered five pages
 * that never did while a 500 on the same request reported the failure honestly.
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const search = searchParams.get('search') || '';
  const recent = searchParams.get('recent') === 'true';

  const backendParams = new URLSearchParams();
  if (search) backendParams.set('search', search);
  if (recent) backendParams.set('recent', 'true');
  const queryString = backendParams.toString();

  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }

  const res = await backendRequest(
    `/workspaces/${encodeURIComponent(workspaceId)}/pages${queryString ? `?${queryString}` : ''}`,
    { method: 'GET' },
    sessionCookie
  );

  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch pages');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const pages = (await res.json()) as WikiPageSummary[];
  return NextResponse.json({ pages });
}

export async function POST(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }

  const body = await request.text();
  const res = await backendRequest(
    `/workspaces/${encodeURIComponent(workspaceId)}/pages`,
    { method: 'POST', body },
    sessionCookie
  );

  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to create page');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const data = (await res.json()) as Record<string, unknown>;
  return NextResponse.json(data, { status: 201 });
}
