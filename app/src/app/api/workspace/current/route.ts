import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

import {
  currentWorkspaceResponse,
  type WorkspaceLookup
} from '@/features/workspace/lib/current-workspace';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

/**
 * Ask the backend which workspaces this session belongs to, and report what
 * asking actually produced — including "nothing", which is a different answer
 * from "an empty list".
 */
async function askBackend(sessionCookie: string): Promise<WorkspaceLookup> {
  try {
    const res = await fetch(`${BACKEND_URL}/workspaces`, {
      headers: { Cookie: `session_token=${sessionCookie}` },
      cache: 'no-store'
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
      return {
        kind: 'refused',
        status: res.status,
        detail: typeof body?.detail === 'string' ? body.detail : null
      };
    }
    return { kind: 'answered', rows: await res.json().catch(() => null) };
  } catch {
    return { kind: 'unreachable' };
  }
}

/**
 * The status codes are the contract here, so they are stated: 401 no session,
 * the backend's own status when it refuses, 503 when it is not answering, 502
 * when a 200 turns out not to be the documented array, and 404 only when the
 * backend said this account has no workspace. See
 * `features/workspace/lib/current-workspace.ts` for why the last one is not a
 * synonym for the others.
 */
export async function GET() {
  const sessionCookie = await getSessionCookie();
  const lookup: WorkspaceLookup = sessionCookie
    ? await askBackend(sessionCookie)
    : { kind: 'no-session' };
  const { status, body } = currentWorkspaceResponse(lookup);
  return NextResponse.json(body, { status });
}
