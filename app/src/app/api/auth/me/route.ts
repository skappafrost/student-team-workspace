import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/** Return the current authenticated user (proxies to the backend /auth/me). */
export async function GET() {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) {
    return NextResponse.json({ user: null }, { status: 401 });
  }

  const res = await fetch(`${BACKEND_URL}/auth/me`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });

  if (!res.ok) {
    return NextResponse.json({ user: null }, { status: res.status });
  }

  const user = (await res.json()) as Record<string, unknown>;
  return NextResponse.json({ user });
}
