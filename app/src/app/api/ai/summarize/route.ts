import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

export async function POST(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;

  const res = await fetch(`${BACKEND_URL}/ai/summarize`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`
    },
    body: JSON.stringify(body),
    cache: 'no-store'
  });

  const data = (await res.json().catch(() => ({ error: 'Failed to summarize' }))) as Record<
    string,
    unknown
  >;

  if (!res.ok) {
    return NextResponse.json(
      { error: data.detail || data.error || 'Failed to summarize' },
      { status: res.status }
    );
  }

  return NextResponse.json(data);
}
