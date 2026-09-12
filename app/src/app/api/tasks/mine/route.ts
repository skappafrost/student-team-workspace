import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/** Current user's tasks across all workspaces (F07 deadlines view). */
export async function GET(request: Request) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) {
    return NextResponse.json({ tasks: [] });
  }

  const url = new URL(request.url);
  const qs = url.searchParams.toString();
  const res = await fetch(`${BACKEND_URL}/users/me/tasks${qs ? `?${qs}` : ''}`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });

  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch tasks');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const tasks = (await res.json()) as Array<Record<string, unknown>>;
  return NextResponse.json({ tasks });
}
