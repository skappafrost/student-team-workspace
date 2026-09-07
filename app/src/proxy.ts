import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

/**
 * Route guard for the Student Team Workspace app.
 *
 * Next.js 16 renamed the middleware file convention to `proxy` (see
 * https://nextjs.org/docs/messages/middleware-to-proxy); this file is the
 * request interceptor previously known as `middleware.ts`.
 *
 * - `/dashboard/:path*` requires the `session_token` cookie. Unauthenticated
 *   requests are redirected to `/auth/sign-in`.
 * - `/auth/:path*` from an authenticated session redirects to `/dashboard/overview`.
 * - Public routes and static assets pass through unchanged.
 *
 * The proxy runs only for the matcher below, so static assets and `_next`
 * bundles are excluded.
 */
export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const hasSession = Boolean(request.cookies.get('session_token')?.value);

  if (pathname.startsWith('/auth/') && hasSession) {
    return NextResponse.redirect(new URL('/dashboard/overview', request.url));
  }

  if (pathname.startsWith('/dashboard/') && !hasSession) {
    const signInUrl = new URL('/auth/sign-in', request.url);
    signInUrl.searchParams.set('from', pathname);
    return NextResponse.redirect(signInUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/auth/:path*']
};
