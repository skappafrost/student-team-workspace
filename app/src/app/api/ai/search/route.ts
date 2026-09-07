import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

export async function GET(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ results: [] });
  }

  const { searchParams } = new URL(request.url);
  const q = searchParams.get('q') || '';
  const scope = searchParams.get('scope') || 'tasks,pages,messages';

  if (!q.trim()) {
    return NextResponse.json({ results: [] });
  }

  const query = new URLSearchParams({ q, scope });
  const res = await fetch(`${BACKEND_URL}/ai/search?${query.toString()}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`
    },
    cache: 'no-store'
  });

  const data = (await res.json().catch(() => ({ error: 'Failed to search' }))) as Record<
    string,
    unknown
  >;

  if (!res.ok) {
    return NextResponse.json(
      { error: data.detail || data.error || 'Failed to search', results: [] },
      { status: res.status }
    );
  }

  return NextResponse.json(data);
}
