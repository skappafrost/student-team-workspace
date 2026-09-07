import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { seededInvites } from '@/features/workspace/fixture';
import { WorkspaceRole } from '@/features/workspace/types';

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

function isBackendWired(sessionCookie: string): Promise<boolean> {
  return fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  })
    .then((res) => res.ok)
    .catch(() => false);
}

export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie || !(await isBackendWired(sessionCookie))) {
    return NextResponse.json({ invites: seededInvites });
  }
  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ invites: seededInvites });
  }
  const res = await backendRequest(
    `/workspaces/${workspaceId}/invites`,
    { method: 'GET' },
    sessionCookie
  );
  if (!res.ok) {
    return NextResponse.json({ error: 'Failed to fetch invites' }, { status: res.status });
  }
  const invites = (await res.json()) as Array<Record<string, unknown>>;
  return NextResponse.json({ invites });
}

export async function POST(request: Request) {
  const sessionCookie = await getSessionCookie();
  const body = (await request.json().catch(() => ({}))) as {
    email?: string;
    role?: WorkspaceRole;
  };
  if (!body.email || !body.role) {
    return NextResponse.json({ error: 'email and role are required' }, { status: 400 });
  }

  if (!sessionCookie || !(await isBackendWired(sessionCookie))) {
    const invite = {
      id: `inv_${Date.now()}`,
      email: body.email,
      role: body.role,
      created_at: new Date().toISOString()
    };
    seededInvites.push({
      id: invite.id,
      email: invite.email,
      role: invite.role,
      invitedAt: invite.created_at
    });
    return NextResponse.json({ invite, invites: seededInvites });
  }

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }
  const res = await backendRequest(
    `/workspaces/${workspaceId}/invites`,
    {
      method: 'POST',
      body: JSON.stringify({ email: body.email, role: body.role })
    },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to send invitation');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const invite = (await res.json()) as Record<string, unknown>;
  const listRes = await backendRequest(
    `/workspaces/${workspaceId}/invites`,
    { method: 'GET' },
    sessionCookie
  );
  const invites = listRes.ok ? ((await listRes.json()) as Array<Record<string, unknown>>) : [];
  return NextResponse.json({ invite, invites });
}

export async function PATCH(request: Request) {
  const sessionCookie = await getSessionCookie();
  const body = (await request.json().catch(() => ({}))) as {
    inviteId?: string;
    role?: WorkspaceRole;
  };
  if (!body.inviteId || !body.role) {
    return NextResponse.json({ error: 'inviteId and role are required' }, { status: 400 });
  }

  if (!sessionCookie || !(await isBackendWired(sessionCookie))) {
    const idx = seededInvites.findIndex((i) => i.id === body.inviteId);
    if (idx !== -1) {
      seededInvites[idx] = { ...seededInvites[idx], role: body.role as WorkspaceRole };
    }
    return NextResponse.json({ invites: seededInvites });
  }

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }
  const res = await backendRequest(
    `/workspaces/${workspaceId}/invites/${encodeURIComponent(body.inviteId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ role: body.role })
    },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to update invite role');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const listRes = await backendRequest(
    `/workspaces/${workspaceId}/invites`,
    { method: 'GET' },
    sessionCookie
  );
  const invites = listRes.ok ? ((await listRes.json()) as Array<Record<string, unknown>>) : [];
  return NextResponse.json({ invites });
}

export async function DELETE(request: Request) {
  const sessionCookie = await getSessionCookie();
  const { searchParams } = new URL(request.url);
  const inviteId = searchParams.get('inviteId');
  if (!inviteId) {
    return NextResponse.json({ error: 'inviteId is required' }, { status: 400 });
  }

  if (!sessionCookie || !(await isBackendWired(sessionCookie))) {
    const idx = seededInvites.findIndex((i) => i.id === inviteId);
    if (idx !== -1) seededInvites.splice(idx, 1);
    return NextResponse.json({ invites: seededInvites });
  }

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }
  const res = await backendRequest(
    `/workspaces/${workspaceId}/invites/${encodeURIComponent(inviteId)}`,
    { method: 'DELETE' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to cancel invite');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const listRes = await backendRequest(
    `/workspaces/${workspaceId}/invites`,
    { method: 'GET' },
    sessionCookie
  );
  const invites = listRes.ok ? ((await listRes.json()) as Array<Record<string, unknown>>) : [];
  return NextResponse.json({ invites });
}
