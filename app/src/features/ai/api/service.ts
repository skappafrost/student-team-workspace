import { SummarizePayload, SummarizeResponse, AISearchResponse, AISearchResult } from './types';
import { createApiClient } from '@/lib/api-client';

const apiRequest = createApiClient('/api/ai');


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
