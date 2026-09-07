import { SummarizePayload, SummarizeResponse, AISearchResponse, AISearchResult } from './types';

async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api/ai${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string>)
    },
    credentials: 'include'
  });

  const data = (await res.json().catch(() => ({}))) as T & { error?: string; detail?: string };
  if (!res.ok) {
    throw new Error(data.error || data.detail || `AI API error: ${res.status}`);
  }
  return data;
}

export async function summarize({ kind, ref_id }: SummarizePayload): Promise<string> {
  const data = await apiRequest<SummarizeResponse>('/summarize', {
    method: 'POST',
    body: JSON.stringify({ kind, ref_id })
  });
  return data.summary || 'No summary available.';
}

export async function searchAI(
  q: string,
  scope = 'tasks,pages,messages'
): Promise<AISearchResult[]> {
  const data = await apiRequest<AISearchResponse>(
    `/search?q=${encodeURIComponent(q)}&scope=${encodeURIComponent(scope)}`
  );
  return data.results || [];
}
