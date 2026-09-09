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

  const body = await request.text();
  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`
    },
    body,
    cache: 'no-store'
  });

  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to create workspace');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const data = (await res.json()) as Record<string, unknown>;
  return NextResponse.json({ workspace: data }, { status: 201 });
}
