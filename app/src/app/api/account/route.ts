import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

/** Export the current user's data as JSON (S03). Streams through the file download. */
export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const res = await fetch(`${BACKEND_URL}/users/me/export`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to export data');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const body = await res.text();
  return new NextResponse(body, {
    headers: {
      'Content-Type': 'application/json',
      'Content-Disposition':
        res.headers.get('content-disposition') ?? 'attachment; filename="stw-export.json"'
    }
  });
}

/** Delete the current user's account (password confirmed). */
export async function DELETE(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const body = (await request.json().catch(() => ({}))) as { password?: string };
  if (!body.password) {
    return NextResponse.json({ error: 'Password is required' }, { status: 400 });
  }

  const res = await fetch(`${BACKEND_URL}/users/me`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`
    },
    body: JSON.stringify({ password: body.password })
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to delete account');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const out = NextResponse.json({ ok: true });
  out.cookies.set('session_token', '', { httpOnly: true, path: '/', maxAge: 0 });
  return out;
}
