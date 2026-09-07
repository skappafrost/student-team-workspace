import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type { Notification } from '@/features/notifications/api/types';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

async function getSessionCookie(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get('session_token')?.value;
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

export async function GET() {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ notifications: [] });
  }

  const res = await backendRequest('/notifications', { method: 'GET' }, sessionCookie);
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to fetch notifications');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const notifications = (await res.json()) as Notification[];
  return NextResponse.json({ notifications });
}

export async function PATCH(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const body = (await request.json().catch(() => ({}))) as { id?: string };
  if (!body.id) {
    return NextResponse.json({ error: 'Missing notification id' }, { status: 400 });
  }

  const res = await backendRequest(
    `/notifications/${body.id}`,
    { method: 'PATCH', body: JSON.stringify({ read: true }) },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to mark notification as read');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  const notification = (await res.json()) as Notification;
  return NextResponse.json({ notification });
}

export async function POST(request: Request) {
  const sessionCookie = await getSessionCookie();
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const body = (await request.json().catch(() => ({}))) as { action?: string };
  if (body.action !== 'mark-all-read') {
    return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
  }

  const res = await backendRequest(
    '/notifications/mark-all-read',
    { method: 'POST' },
    sessionCookie
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to mark all notifications as read');
    return NextResponse.json({ error: text }, { status: res.status });
  }
  return NextResponse.json({ ok: true });
}
