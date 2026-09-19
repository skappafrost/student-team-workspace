import { NextResponse } from 'next/server';
import { getSessionCookie, listWorkspaces } from '@/lib/server-workspace';

/** List every workspace the session user belongs to. */
export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ workspaces: [] });
  }
  const workspaces = await listWorkspaces(sessionCookie);
  return NextResponse.json({ workspaces });
}
