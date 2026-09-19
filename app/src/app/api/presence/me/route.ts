import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

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

/**
 * Sets the caller's own status. `POST`, and `200` rather than `201`: the backend
 * upserts one row per (workspace, user), so there is no new resource to point at.
 * Sending `status_message: null` clears the message — that is the contract, not
 * an omission, so this handler must forward the key rather than strip nulls.
 */
export async function POST(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== 'object') {
    return NextResponse.json({ error: 'A status payload is required' }, { status: 400 });
  }
  const res = await fetch(
    `${BACKEND_URL}/workspaces/${encodeURIComponent(workspaceId)}/presence/me`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Cookie: `session_token=${sessionCookie}` },
      body: JSON.stringify(body)
    }
  );
  const out = (await res.json().catch(() => null)) as { detail?: string } | null;
  if (!res.ok) {
    return NextResponse.json(
      { error: out?.detail ?? 'Failed to set presence' },
      { status: res.status }
    );
  }
  return NextResponse.json(out, { status: 200 });
}
