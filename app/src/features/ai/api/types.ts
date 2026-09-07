export interface SummarizeResponse {
  summary: string;
}

export type SummaryKind = 'task' | 'page' | 'channel';

export interface SummarizePayload {
  kind: SummaryKind;
  ref_id: string;
}

export interface AISearchResult {
  kind: string;
  id: string;
  title: string;
  snippet: string;
  workspace_id: string;
  score: number;
}

export interface AISearchResponse {
  results: AISearchResult[];
}
