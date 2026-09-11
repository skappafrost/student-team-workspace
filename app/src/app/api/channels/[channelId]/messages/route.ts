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

export async function GET(
  request: Request,
  { params }: { params: Promise<{ channelId: string }> }
) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ messages: [] });
  }
  const { channelId } = await params;
  const q = new URL(request.url).searchParams.get('q');
  const qs = q && q.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
  const res = await backendRequest(
    `/channels/${encodeURIComponent(channelId)}/messages${qs}`,
    { method: 'GET' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch messages');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const messages = (await res.json()) as Array<Record<string, unknown>>;
  return NextResponse.json({ messages });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ channelId: string }> }
) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }
  const { channelId } = await params;
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const res = await backendRequest(
    `/channels/${encodeURIComponent(channelId)}/messages`,
    {
      method: 'POST',
      body: JSON.stringify(body)
    },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to create message');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const message = (await res.json()) as Record<string, unknown>;
  return NextResponse.json({ message });
}
