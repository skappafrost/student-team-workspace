import { NextResponse } from 'next/server';
import { getSessionCookie, getCurrentWorkspaceId } from '@/lib/server-workspace';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getWorkspaceAndSession(): Promise<{
  sessionCookie: string;
  workspaceId: string;
} | null> {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) return null;
  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) return null;
  return { sessionCookie, workspaceId };
}

/** List the current user's DM channels. */
export async function GET() {
  const ctx = await getWorkspaceAndSession();
  if (!ctx) return NextResponse.json({ dms: [] });
  const res = await fetch(
    `${BACKEND_URL}/workspaces/${encodeURIComponent(ctx.workspaceId)}/dms`,
    { headers: { Cookie: `session_token=${ctx.sessionCookie}` }, cache: 'no-store' }
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch DMs');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const dms = (await res.json()) as Array<Record<string, unknown>>;
  return NextResponse.json({ dms });
}

/** Create (or return existing) DM channel with another member. */
export async function POST(request: Request) {
  const ctx = await getWorkspaceAndSession();
  if (!ctx) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const res = await fetch(
    `${BACKEND_URL}/workspaces/${encodeURIComponent(ctx.workspaceId)}/dms`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: `session_token=${ctx.sessionCookie}`
      },
      body: JSON.stringify(body),
      cache: 'no-store'
    }
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to create DM');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const dm = (await res.json()) as Record<string, unknown>;
  return NextResponse.json({ dm });
}
