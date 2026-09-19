import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { WikiPageSummary } from '@/features/wiki/api/types';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

const MOCK_PAGES: WikiPageSummary[] = [
  {
    id: 'page-1',
    parent_id: null,
    title: 'Getting Started',
    slug: 'getting-started'
  },
  {
    id: 'page-2',
    parent_id: null,
    title: 'Engineering',
    slug: 'engineering'
  },
  {
    id: 'page-3',
    parent_id: 'page-2',
    title: 'Frontend',
    slug: 'frontend'
  },
  {
    id: 'page-4',
    parent_id: 'page-2',
    title: 'Backend',
    slug: 'backend'
  },
  {
    id: 'page-5',
    parent_id: 'page-3',
    title: 'React Guidelines',
    slug: 'react-guidelines'
  }
];

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
}

async function getCurrentWorkspaceId(sessionCookie: string): Promise<string | null> {
  const res = await fetch(`${BACKEND_URL}/workspaces`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });
  if (!res.ok) return null;
  const data = (await res.json()) as Array<{ id: string }>;
  if (!Array.isArray(data) || data.length === 0) return null;
  return data[0].id;
}

async function backendRequest(
  path: string,
  init: RequestInit,
  sessionCookie: string
): Promise<Response> {
  return fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Cookie: `session_token=${sessionCookie}`,
      ...(init.headers as Record<string, string>)
    },
    cache: 'no-store'
  });
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const search = searchParams.get('search') || '';
  const recent = searchParams.get('recent') === 'true';

  const backendParams = new URLSearchParams();
  if (search) backendParams.set('search', search);
  if (recent) backendParams.set('recent', 'true');
  const queryString = backendParams.toString();

  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ pages: MOCK_PAGES });
  }

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ pages: MOCK_PAGES });
  }

  const res = await backendRequest(
    `/workspaces/${encodeURIComponent(workspaceId)}/pages${queryString ? `?${queryString}` : ''}`,
    { method: 'GET' },
    sessionCookie
  );

  if (res.status === 404) {
    return NextResponse.json({ pages: MOCK_PAGES });
  }

  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch pages');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const pages = (await res.json()) as WikiPageSummary[];
  return NextResponse.json({ pages });
}

export async function POST(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const workspaceId = await getCurrentWorkspaceId(sessionCookie);
  if (!workspaceId) {
    return NextResponse.json({ error: 'No workspace found' }, { status: 404 });
  }

  const body = await request.text();
  const res = await backendRequest(
    `/workspaces/${encodeURIComponent(workspaceId)}/pages`,
    { method: 'POST', body },
    sessionCookie
  );

  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to create page');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  const data = (await res.json()) as Record<string, unknown>;
  return NextResponse.json(data, { status: 201 });
}
