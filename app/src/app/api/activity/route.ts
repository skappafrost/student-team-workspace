import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/** Workspace activity feed (R03). Resolves the current workspace = first of GET /workspaces. */
export async function GET() {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) {
    return NextResponse.json({ activities: [] });
  }

  const headers = { Cookie: `session_token=${sessionCookie}` };
  const wsRes = await fetch(`${BACKEND_URL}/workspaces`, { headers, cache: 'no-store' });
  if (!wsRes.ok) {
    return NextResponse.json({ activities: [] });
  }
  const workspaces = (await wsRes.json()) as Array<{ id: string }>;
  const workspaceId = workspaces[0]?.id;
  if (!workspaceId) {
    return NextResponse.json({ activities: [] });
  }

  const res = await fetch(`${BACKEND_URL}/workspaces/${workspaceId}/activity`, {
    headers,
    cache: 'no-store'
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch activity');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const activities = (await res.json()) as Array<Record<string, unknown>>;
  return NextResponse.json({ activities });
}
