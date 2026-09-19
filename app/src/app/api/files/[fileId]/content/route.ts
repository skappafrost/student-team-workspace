import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/**
 * Stream a file's bytes through the BFF. The backend returns a relative
 * `/uploads/<key>` URL that only resolves on the API origin, so the client
 * cannot fetch it directly — this route looks up the record and proxies it.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ fileId: string }> }) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session_token')?.value;
  if (!sessionCookie) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const { fileId } = await params;
  const headers = { Cookie: `session_token=${sessionCookie}` };

  const recordRes = await fetch(`${BACKEND_URL}/files/${encodeURIComponent(fileId)}`, {
    headers,
    cache: 'no-store'
  });
  if (!recordRes.ok) {
    return NextResponse.json({ error: 'File not found' }, { status: recordRes.status });
  }
  const record = (await recordRes.json()) as { url?: string; type?: string };
  if (!record.url) {
    return NextResponse.json({ error: 'File has no content URL' }, { status: 404 });
  }

  // Only ever proxy a relative /uploads/<key> path on the API origin. Anything
  // else (absolute URL, scheme-relative, path escape) is refused — otherwise a
  // poisoned record.url would turn this route into an SSRF/hijack vector.
  const contentPath = record.url;
  if (
    !contentPath.startsWith('/uploads/') ||
    contentPath.startsWith('//') ||
    contentPath.includes('..') ||
    /[\s]/.test(contentPath)
  ) {
    return NextResponse.json({ error: 'Unexpected content URL' }, { status: 502 });
  }

  const contentRes = await fetch(`${BACKEND_URL}${contentPath}`, {
    headers,
    cache: 'no-store'
  });
  if (!contentRes.ok) {
    return NextResponse.json({ error: 'Content fetch failed' }, { status: contentRes.status });
  }

  return new NextResponse(contentRes.body, {
    headers: {
      'Content-Type':
        record.type || contentRes.headers.get('content-type') || 'application/octet-stream'
    }
  });
}
