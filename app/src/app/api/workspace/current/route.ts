import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ workspace: null });
  }

  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });

  if (!res.ok) {
    return NextResponse.json({ workspace: null });
  }

  const data = (await res.json()) as Array<{ id: string; name?: string }>;
  if (!Array.isArray(data) || data.length === 0) {
    return NextResponse.json({ workspace: null });
  }

  return NextResponse.json({ workspace: { id: data[0].id, name: data[0].name ?? 'Workspace' } });
}
