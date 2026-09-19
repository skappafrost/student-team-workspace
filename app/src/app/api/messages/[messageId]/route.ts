import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function proxyToBackend(request: Request, messageId: string, method: string) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const body =
    method === 'DELETE'
      ? undefined
      : JSON.stringify((await request.json().catch(() => ({}))) as Record<string, unknown>);

  const res = await fetch(`${BACKEND_URL}/messages/${encodeURIComponent(messageId)}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`
    },
    body,
    cache: 'no-store'
  });

  if (!res.ok) {
    const text = await res.text().catch(() => `Failed to ${method} message`);
    return NextResponse.json({ error: text }, { status: res.status });
  }

  if (method === 'DELETE') {
    return new NextResponse(null, { status: 204 });
  }

  const message = (await res.json()) as Record<string, unknown>;
  return NextResponse.json({ message });
}

/** Edit a message's content (proxies PATCH to the backend). */
export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ messageId: string }> }
) {
  const { messageId } = await params;
  return proxyToBackend(request, messageId, 'PATCH');
}

/** Delete a message (proxies DELETE to the backend). */
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ messageId: string }> }
) {
  const { messageId } = await params;
  return proxyToBackend(request, messageId, 'DELETE');
}
