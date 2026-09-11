import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getWorkspaceAndSession(): Promise<{
  sessionCookie: string;
  workspaceId: string;
} | null> {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) return null;
  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  if (!res.ok) return null;
  const data = (await res.json()) as Array<{ id: string }>;
  if (!Array.isArray(data) || data.length === 0) return null;
  return { sessionCookie, workspaceId: data[0].id };
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
