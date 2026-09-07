import { cookies } from 'next/headers';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export interface WorkspaceSummary {
  id: string;
  name: string;
}

export async function getCurrentWorkspace(): Promise<WorkspaceSummary | null> {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) return null;

  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });

  if (!res.ok) return null;

  const data = (await res.json()) as Array<{ id: string; name?: string }>;
  if (!Array.isArray(data) || data.length === 0) return null;

  return { id: data[0].id, name: data[0].name ?? 'Workspace' };
}
