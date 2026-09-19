import { NextResponse } from 'next/server';
import { getSessionCookie, getCurrentWorkspaceId, listWorkspaces } from '@/lib/server-workspace';

export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ workspace: null });
  }

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ workspace: null });
  }

  const workspaces = await listWorkspaces(sessionCookie);
  const current = workspaces.find((w) => w.id === workspaceId);
  return NextResponse.json({
    workspace: { id: workspaceId, name: current?.name ?? 'Workspace' }
  });
}
