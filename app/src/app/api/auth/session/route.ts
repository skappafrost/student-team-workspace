import { NextResponse } from 'next/server';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface AuthBody {
  kind?: unknown;
  email?: unknown;
  password?: unknown;
}

/** Proxy auth requests to the backend and forward the httpOnly Set-Cookie header. */
async function proxyAuth(kind: 'login' | 'register', body: AuthBody): Promise<NextResponse> {
  const { email, password } = body;
  if (typeof email !== 'string' || typeof password !== 'string' || !email || !password) {
    return NextResponse.json({ error: 'Email and password are required' }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/auth/${kind}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });
  } catch {
    return NextResponse.json({ error: 'Auth service unreachable' }, { status: 502 });
  }

  const upstreamBody = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;

  if (!upstream.ok) {
    return NextResponse.json(
      { error: upstreamBody.error ?? upstreamBody.message ?? 'Authentication failed' },
      { status: upstream.status }
    );
  }

  const token =
    typeof upstreamBody.access_token === 'string'
      ? upstreamBody.access_token
      : typeof upstreamBody.token === 'string'
        ? upstreamBody.token
        : undefined;
  if (!token) {
    return NextResponse.json({ error: 'Auth service returned no token' }, { status: 502 });
  }

  const res = NextResponse.json({ user: upstreamBody.user ?? null });

  // Forward the backend's Set-Cookie if it sets a cookie with the token;
  // otherwise set our own httpOnly cookie. Either way the token never reaches JS.
  const setCookie = upstream.headers.get('set-cookie');
  if (setCookie) {
    res.headers.set('Set-Cookie', setCookie);
  } else {
    res.cookies.set('session_token', token, {
      httpOnly: true,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: 60 * 60 * 24 * 7 // 7 days
    });
  }

  return res;
}

/** Exchange credentials for a session and store the token as an httpOnly cookie. */
export async function POST(request: Request): Promise<NextResponse> {
  let body: AuthBody;
  try {
    body = (await request.json()) as AuthBody;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  const kind = body.kind === 'register' ? 'register' : 'login';
  return proxyAuth(kind, body);
}

/** Clear the session cookie; revokes the backend session (jti) when present. */
export async function DELETE(request: Request): Promise<NextResponse> {
  const sessionCookie = request.headers
    .get('cookie')
    ?.match(/(?:^|;\s*)session_token=([^;]+)/)?.[1];

  let upstream: Response | undefined;
  try {
    upstream = await fetch(`${API_URL}/auth/logout`, {
      method: 'POST',
      headers: sessionCookie ? { Cookie: `session_token=${sessionCookie}` } : {}
    });
  } catch {
    // Best-effort call to the backend; still clear the cookie below.
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set('session_token', '', { httpOnly: true, path: '/', maxAge: 0 });

  // If the backend returned its own Set-Cookie to clear the cookie, prefer it.
  const setCookie = upstream?.headers.get('set-cookie');
  if (setCookie) {
    res.headers.set('Set-Cookie', setCookie);
  }

  return res;
}

/** Sign out everywhere: revoke ALL backend sessions for the user (S02). */
export async function PATCH(request: Request): Promise<NextResponse> {
  const sessionCookie = request.headers
    .get('cookie')
    ?.match(/(?:^|;\s*)session_token=([^;]+)/)?.[1];
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  try {
    await fetch(`${API_URL}/auth/logout-all`, {
      method: 'POST',
      headers: { Cookie: `session_token=${sessionCookie}` }
    });
  } catch {
    // Best-effort; still clear the local cookie below.
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set('session_token', '', { httpOnly: true, path: '/', maxAge: 0 });
  return res;
}
