import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/**
 * `GET /workspaces/{id}/presence` — the whole roster, one request.
 *
 * The backend documents this endpoint as deliberately unpaginated and unordered
 * because a client cannot render "who is online" from a page of it, so this
 * handler stays a thin proxy: no merging, no sorting, no synthetic entries. A
 * guest gets the backend's `403 "Guests cannot use presence"` forwarded as-is —
 * the status code is the only role signal the client has, and inventing an empty
 * array here would make a permission answer look like "nobody is online".
 */
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

export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }
  const res = await fetch(`${BACKEND_URL}/workspaces/${encodeURIComponent(workspaceId)}/presence`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  const body = (await res.json().catch(() => null)) as unknown;
  if (!res.ok) {
    return NextResponse.json(
      { error: (body as { detail?: string })?.detail ?? 'Failed to fetch presence' },
      { status: res.status }
    );
  }
  return NextResponse.json(body, { status: 200 });
}
