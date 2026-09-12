import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
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

/** Backend page routes are workspace-scoped; resolve the current workspace. */
async function resolveWorkspaceId(sessionCookie: string): Promise<string | null> {
  const res = await backendRequest('/workspaces', { method: 'GET' }, sessionCookie);
  if (!res.ok) return null;
  const workspaces = (await res.json()) as Array<{ id: string }>;
  return workspaces[0]?.id ?? null;
}

async function proxy(
  request: Request,
  pageId: string,
  method: 'GET' | 'PATCH' | 'DELETE'
): Promise<NextResponse> {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const workspaceId = await resolveWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace' }, { status: 404 });
  }

  const init: RequestInit = { method };
  if (method === 'PATCH') {
    init.body = JSON.stringify(await request.json().catch(() => ({})));
  }

  const res = await backendRequest(
    `/workspaces/${workspaceId}/pages/${encodeURIComponent(pageId)}`,
    init,
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => `Failed to ${method.toLowerCase()} page`);
    return NextResponse.json({ error: text }, { status: res.status });
  }
  if (method === 'DELETE') {
    return NextResponse.json({ ok: true });
  }
  const page = (await res.json()) as Record<string, unknown>;
  return NextResponse.json({ page });
}

export async function GET(request: Request, { params }: { params: Promise<{ pageId: string }> }) {
  const { pageId } = await params;
  return proxy(request, pageId, 'GET');
}

export async function PATCH(request: Request, { params }: { params: Promise<{ pageId: string }> }) {
  const { pageId } = await params;
  return proxy(request, pageId, 'PATCH');
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ pageId: string }> }
) {
  const { pageId } = await params;
  return proxy(request, pageId, 'DELETE');
}
