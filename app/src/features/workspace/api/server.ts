import { getSessionCookie, getCurrentWorkspaceId, listWorkspaces } from '@/lib/server-workspace';

export interface WorkspaceSummary {
  id: string;
  name: string;
}

export async function getCurrentWorkspace(): Promise<WorkspaceSummary | null> {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) return null;

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) return null;

  const workspaces = await listWorkspaces(sessionCookie);
  const current = workspaces.find((w) => w.id === workspaceId);
  return { id: workspaceId, name: current?.name ?? 'Workspace' };
}
