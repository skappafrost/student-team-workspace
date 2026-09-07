import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

async function getCurrentWorkspaceId(sessionCookie: string): Promise<string | null> {
  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  if (!res.ok) return null;
  const data = (await res.json()) as Array<{ id: string }>;
  if (!Array.isArray(data) || data.length === 0) return null;
  return data[0].id;
}

async function backendRequest(
  path: string,
  init: RequestInit,
  sessionCookie: string
): Promise<Response> {
  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`,
      ...(init.headers as Record<string, string>)
    },
    cache: 'no-store'
  });
}

export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ projects: [] });
  }
  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ projects: [] });
  }
  const res = await backendRequest(
    `/workspaces/${workspaceId}/projects`,
    { method: 'GET' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch projects');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const projects = (await res.json()) as Array<Record<string, unknown>>;
  return NextResponse.json({ projects });
}

export async function POST(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }
  const res = await backendRequest(
    `/workspaces/${workspaceId}/projects`,
    {
      method: 'POST',
      body: JSON.stringify(body)
    },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to create project');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const project = (await res.json()) as Record<string, unknown>;
  const listRes = await backendRequest(
    `/workspaces/${workspaceId}/projects`,
    { method: 'GET' },
    sessionCookie
  );
  const projects = listRes.ok ? ((await listRes.json()) as Array<Record<string, unknown>>) : [];
  return NextResponse.json({ project, projects });
}

export async function PATCH(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const body = (await request.json().catch(() => ({}))) as { projectId?: string } & Record<
    string,
    unknown
  >;
  const { projectId, ...payload } = body;
  if (!projectId) {
    return NextResponse.json({ error: 'projectId is required' }, { status: 400 });
  }
  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }
  const res = await backendRequest(
    `/projects/${encodeURIComponent(projectId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload)
    },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to update project');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const project = (await res.json()) as Record<string, unknown>;
  const listRes = await backendRequest(
    `/workspaces/${workspaceId}/projects`,
    { method: 'GET' },
    sessionCookie
  );
  const projects = listRes.ok ? ((await listRes.json()) as Array<Record<string, unknown>>) : [];
  return NextResponse.json({ project, projects });
}

export async function DELETE(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const { searchParams } = new URL(request.url);
  const projectId = searchParams.get('projectId');
  if (!projectId) {
    return NextResponse.json({ error: 'projectId is required' }, { status: 400 });
  }
  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }
  const res = await backendRequest(
    `/projects/${encodeURIComponent(projectId)}`,
    { method: 'DELETE' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to delete project');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const listRes = await backendRequest(
    `/workspaces/${workspaceId}/projects`,
    { method: 'GET' },
    sessionCookie
  );
  const projects = listRes.ok ? ((await listRes.json()) as Array<Record<string, unknown>>) : [];
  return NextResponse.json({ projects });
}
