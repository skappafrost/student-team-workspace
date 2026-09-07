import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { WikiPage, WikiPageSummary } from '@/features/wiki/api/types';

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

const MOCK_PAGE_MAP: Record<string, WikiPage> = {
  'page-1': {
    id: 'page-1',
    workspace_id: 'ws-1',
    parent_id: null,
    title: 'Getting Started',
    slug: 'getting-started',
    content:
      '# Getting Started\n\nWelcome to the workspace wiki. This is a placeholder page rendered from mock data while the backend pages API is being implemented.\n\n## Quick links\n\n- Engineering\n- Frontend\n- Backend',
    created_by: 'dev',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  },
  'page-2': {
    id: 'page-2',
    workspace_id: 'ws-1',
    parent_id: null,
    title: 'Engineering',
    slug: 'engineering',
    content:
      '# Engineering\n\nEngineering team knowledge base.\n\n## Sub-pages\n\n- Frontend\n- Backend',
    created_by: 'dev',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  },
  'page-3': {
    id: 'page-3',
    workspace_id: 'ws-1',
    parent_id: 'page-2',
    title: 'Frontend',
    slug: 'frontend',
    content: '# Frontend\n\nFrontend guidelines and best practices.',
    created_by: 'dev',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  },
  'page-4': {
    id: 'page-4',
    workspace_id: 'ws-1',
    parent_id: 'page-2',
    title: 'Backend',
    slug: 'backend',
    content: '# Backend\n\nBackend architecture and API conventions.',
    created_by: 'dev',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  },
  'page-5': {
    id: 'page-5',
    workspace_id: 'ws-1',
    parent_id: 'page-3',
    title: 'React Guidelines',
    slug: 'react-guidelines',
    content: '# React Guidelines\n\nComponent architecture, hooks, and patterns.',
    created_by: 'dev',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  }
};

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
