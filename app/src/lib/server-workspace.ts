import { cookies } from 'next/headers';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export interface WorkspaceSummary {
  id: string;
  name?: string;
}

/** Session cookie for the current request, or undefined when logged out. */
export async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

/** List the workspaces the session user belongs to. */
export async function listWorkspaces(sessionCookie: string): Promise<WorkspaceSummary[]> {
  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  if (!res.ok) return [];
  const data = (await res.json().catch(() => [])) as WorkspaceSummary[];
  return Array.isArray(data) ? data : [];
}

/**
 * Resolve the active workspace: the `workspace_id` cookie (set by
 * /api/workspace/switch) when it still matches a workspace the user belongs
 * to, otherwise the first workspace in the list.
 */
export async function getCurrentWorkspaceId(sessionCookie: string): Promise<string | null> {
  const workspaces = await listWorkspaces(sessionCookie);
  if (workspaces.length === 0) return null;
  const cookieStore = await cookies();
  const wanted = cookieStore.get('workspace_id')?.value;
  return (workspaces.find((w) => w.id === wanted) ?? workspaces[0]).id;
}
