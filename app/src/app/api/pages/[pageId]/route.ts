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

export async function GET(_request: Request, { params }: { params: Promise<{ pageId: string }> }) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const { pageId } = await params;
  const res = await backendRequest(
    `/pages/${encodeURIComponent(pageId)}`,
    { method: 'GET' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch page');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const page = (await res.json()) as Record<string, unknown>;
  return NextResponse.json({ page });
}

export async function PATCH(request: Request, { params }: { params: Promise<{ pageId: string }> }) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const { pageId } = await params;
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const res = await backendRequest(
    `/pages/${encodeURIComponent(pageId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(body)
    },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to update page');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const page = (await res.json()) as Record<string, unknown>;
  return NextResponse.json({ page });
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ pageId: string }> }
) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const { pageId } = await params;
  const res = await backendRequest(
    `/pages/${encodeURIComponent(pageId)}`,
    { method: 'DELETE' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to delete page');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  return NextResponse.json({ ok: true });
}
