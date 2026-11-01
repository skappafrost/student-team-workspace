import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/**
 * Serve uploaded bytes through the BFF.
 *
 * The backend builds `file.url` as `/uploads/{storage_key}` — a path on *its*
 * origin. Every caller used it as an app-relative path, so the browser asked Next
 * for `/uploads/...`, where no route exists, and downloads failed with a 404 that
 * the click handler swallowed. This is the missing hop, keeping the URL shape the
 * backend already emits.
 *
 * Access control is deliberately not re-implemented here: only `session_token` is
 * forwarded, so the backend's `_resolve_read_file` remains the single decision
 * point — including the private-channel rule. A second rule in the BFF would be a
 * second thing to keep in sync, and it is the one the browser actually reaches.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ key: string }> }
) {
  const { key } = await params;
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const res = await fetch(`${BACKEND_URL}/uploads/${encodeURIComponent(key)}`, {
    headers: { Cookie: `session_token=${sessionCookie}` },
    cache: 'no-store'
  });

  if (!res.ok) {
    const text = await res.text().catch(() => 'Failed to download file');
    return NextResponse.json({ error: text }, { status: res.status });
  }

  // `arrayBuffer`, not `text`: these are PDFs and images. `api/account/route.ts`
  // buffers with `res.text()` because its export is JSON — copying that half here
  // would corrupt every binary download.
  const body = await res.arrayBuffer();
  return new NextResponse(body, {
    headers: {
      'Content-Type': res.headers.get('content-type') ?? 'application/octet-stream',
      'Content-Disposition':
        res.headers.get('content-disposition') ?? `attachment; filename="${encodeURIComponent(key)}"`
    }
  });
}
