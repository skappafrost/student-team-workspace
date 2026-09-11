import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/** Toggle an emoji reaction on a message (proxies to the backend). */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ messageId: string }> }
) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const { messageId } = await params;
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;

  const res = await fetch(
    `${BACKEND_URL}/messages/${encodeURIComponent(messageId)}/reactions`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: `session_token=${sessionCookie}`
      },
      body: JSON.stringify(body),
      cache: 'no-store'
    }
  );

  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to toggle reaction');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const reactions = (await res.json()) as Array<Record<string, unknown>>;
  return NextResponse.json({ reactions });
}
