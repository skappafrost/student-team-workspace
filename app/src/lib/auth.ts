import { redirect } from 'next/navigation';

// ============================================================
// JWT auth client — session via httpOnly cookie
// ============================================================
// Backend endpoints: ${NEXT_PUBLIC_API_URL}/auth/{register,login,refresh,logout}
// The JWT itself never touches JS: it lives in an httpOnly access-token cookie
// managed by the backend and proxied through /api/auth/session route handlers.
// All client-side calls use credentials: 'include' so the browser stores and
// sends the cookie automatically.
// ============================================================

export type SessionUser = {
  id: string;
  name: string;
  email: string;
  role: 'admin' | 'member';
};

type AuthKind = 'login' | 'register';

export type AuthErrorCode = 'network' | 'unauthorized' | 'bad_request' | 'unknown';

export class AuthError extends Error {
  constructor(
    message: string,
    public readonly code: AuthErrorCode,
    public readonly status?: number
  ) {
    super(message);
    this.name = 'AuthError';
  }
}

function readErrorMessage(body: unknown): string {
  // Backend (FastAPI) returns {detail: [...]} arrays on 422 validation errors,
  // plain strings on 401/409, and our proxy wraps upstream errors as {error}.
  if (typeof body !== 'object' || body === null) return 'Authentication failed';
  const b = body as Record<string, unknown>;
  if (Array.isArray(b.detail)) return 'Please check your input and try again.';
  if (typeof b.error === 'string') return b.error;
  if (typeof b.message === 'string') return b.message;
  if (typeof b.detail === 'string') return b.detail;
  return 'Authentication failed';
}

async function postAuth(kind: AuthKind, email: string, password: string): Promise<SessionUser> {
  let res: Response;
  try {
    res = await fetch('/api/auth/session', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, email, password })
    });
  } catch {
    throw new AuthError('Auth service unreachable', 'network');
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = {};
  }

  if (!res.ok) {
    const message = readErrorMessage(body);
    // 401 invalid credentials, 409 duplicate email — both surface inline.
    if (res.status === 401 || res.status === 409) {
      throw new AuthError(message, 'unauthorized', res.status);
    }
    if (res.status === 400 || res.status === 422) {
      throw new AuthError(message, 'bad_request', res.status);
    }
    throw new AuthError(message, 'unknown', res.status);
  }

  const data = body as { user?: SessionUser };
  if (!data.user) {
    throw new AuthError('Auth service returned no user', 'unknown');
  }
  return data.user;
}

/** Sign in an existing user. Sets the httpOnly session cookie on success. */
export async function signIn(email: string, password: string): Promise<SessionUser> {
  return postAuth('login', email, password);
}

/** Register a new user. Sets the httpOnly session cookie on success. */
export async function signUp(email: string, password: string): Promise<SessionUser> {
  return postAuth('register', email, password);
}

/** Sign out. Clears the httpOnly session cookie. */
export async function signOut(): Promise<void> {
  try {
    await fetch('/api/auth/session', {
      method: 'DELETE',
      credentials: 'include'
    });
  } catch {
    // Best-effort: the backend route handler clears the cookie even if the
    // upstream logout fails, so we swallow network errors on the client.
  }
}

// ============================================================
// Authenticated request helper
// ============================================================

export type AuthFetchInit = RequestInit & { redirectOnAuthError?: boolean };

/**
 * Wrapper around fetch that sends credentials on every request and treats 401
 * responses as a signal to redirect to /login. The access token itself is never
 * read or stored in JS — it travels as an httpOnly cookie.
 */
export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: AuthFetchInit = {}
): Promise<Response> {
  const { redirectOnAuthError = true, ...rest } = init;

  let res: Response;
  try {
    res = await fetch(input, {
      ...rest,
      credentials: 'include'
    });
  } catch (err) {
    throw new AuthError(err instanceof Error ? err.message : 'Network error', 'network');
  }

  if (res.status === 401 && redirectOnAuthError) {
    redirect('/auth/sign-in');
  }

  return res;
}

// ============================================================
// Server-side helpers
// ============================================================

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/**
 * Server-side only. Resolves the current user from the backend's /auth/me
 * endpoint using the httpOnly session cookie. Returns null when
 * unauthenticated. Never exposes the token to JS.
 */
export async function getCurrentUser(): Promise<SessionUser | null> {
  const { cookies } = await import('next/headers');
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) return null;

  try {
    const res = await fetch(`${API_URL}/auth/me`, {
      credentials: 'include',
      headers: { Cookie: `session_token=${sessionCookie}` },
      cache: 'no-store'
    });
    if (!res.ok) return null;
    return (await res.json()) as SessionUser;
  } catch {
    return null;
  }
}
