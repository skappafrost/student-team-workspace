import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

export async function GET(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const wsRes = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  if (!wsRes.ok) {
    return NextResponse.json({ error: 'Failed to load workspaces' }, { status: wsRes.status });
  }
  const workspaces = (await wsRes.json()) as Array<{ id: string }>;
  const workspaceId = workspaces[0]?.id;
  if (!workspaceId) {
    return NextResponse.json({ entries: [] });
  }

  const { searchParams } = new URL(request.url);
  const params = new URLSearchParams();
  for (const key of ['verb', 'target_type', 'actor_id', 'q', 'limit', 'offset']) {
    const value = searchParams.get(key);
    if (value) params.set(key, value);
  }
  const suffix = params.size > 0 ? `?${params.toString()}` : '';

  const res = await fetch(`${BACKEND_URL}/workspaces/${workspaceId}/audit-log${suffix}`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  const data = await res.json().catch(() => []);
  if (!res.ok) {
    return NextResponse.json(
      { error: (data as { detail?: string }).detail || 'Failed to load audit log' },
      { status: res.status }
    );
  }
  return NextResponse.json({ entries: data });
}
