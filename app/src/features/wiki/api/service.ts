import { WikiPage, WikiPageSummary, WikiPageVersion } from './types';

async function apiRequest<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api/pages${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string>)
    },
    credentials: 'include'
  });

  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) {
    throw new Error(data.error || `API error: ${res.status}`);
  }
  return data;
}

export async function getPages(): Promise<WikiPageSummary[]> {
  const data = await apiRequest<{ pages: WikiPageSummary[] }>('');
  return data.pages || [];
}

export async function searchPages(q: string, recent = false): Promise<WikiPageSummary[]> {
  const params = new URLSearchParams();
  if (recent) {
    params.set('recent', 'true');
  } else if (q.trim()) {
    params.set('search', q.trim());
  }
  const data = await apiRequest<{ pages: WikiPageSummary[] }>(`?${params.toString()}`);
  return data.pages || [];
}

export async function getPage(id: string): Promise<WikiPage | null> {
  const data = await apiRequest<{ page: WikiPage | null }>(`/${encodeURIComponent(id)}`);
  return data.page ?? null;
}

export async function getPageHistory(id: string): Promise<WikiPageVersion[]> {
  const data = await apiRequest<{ versions: WikiPageVersion[] }>(
    `/${encodeURIComponent(id)}/history`
  );
  return data.versions || [];
}

export async function restorePageVersion(
  id: string,
  version: number
): Promise<WikiPage | null> {
  const data = await apiRequest<{ page: WikiPage | null }>(
    `/${encodeURIComponent(id)}/history`,
    { method: 'POST', body: JSON.stringify({ version }) }
  );
  return data.page ?? null;
}
