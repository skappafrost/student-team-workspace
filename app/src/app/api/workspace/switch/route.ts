import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { getSessionCookie, listWorkspaces } from '@/lib/server-workspace';

/**
 * Set the active workspace. The backend has no switch endpoint (workspace
 * scoping is an explicit path param), so the selection is stored in a
 * `workspace_id` cookie that every BFF route resolves via
 * `@/lib/server-workspace`.
 */
export async function POST(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const body = (await request.json().catch(() => ({}))) as { workspace_id?: string };
  if (!body.workspace_id) {
    return NextResponse.json({ error: 'Missing workspace_id' }, { status: 400 });
  }

  const workspaces = await listWorkspaces(sessionCookie);
  const target = workspaces.find((w) => w.id === body.workspace_id);
  if (!target) {
    return NextResponse.json({ error: 'Not a member of that workspace' }, { status: 403 });
  }

  const cookieStore = await cookies();
  cookieStore.set('workspace_id', target.id, {
    path: '/',
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 365
  });
  return NextResponse.json({ workspace: { id: target.id, name: target.name ?? 'Workspace' } });
}
