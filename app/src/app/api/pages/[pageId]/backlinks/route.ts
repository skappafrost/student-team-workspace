import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/** GET /api/pages/[pageId]/backlinks — pages linking to this one. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ pageId: string }> }
) {
  const { pageId } = await params;
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const wsRes = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  if (!wsRes.ok) {
    return NextResponse.json({ error: 'No workspace' }, { status: wsRes.status });
  }
  const workspaces = (await wsRes.json()) as Array<{ id: string }>;
  const workspaceId = workspaces[0]?.id;
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace' }, { status: 404 });
  }

  const res = await fetch(
    `${BACKEND_URL}/workspaces/${workspaceId}/pages/${encodeURIComponent(pageId)}/backlinks`,
    { headers: { Cookie: `session_token=${sessionCookie}` }, cache: 'no-store' }
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to load backlinks');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  return NextResponse.json({ backlinks: await res.json() });
}
