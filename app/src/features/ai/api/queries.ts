import { queryOptions } from '@tanstack/react-query';
import { summarize, searchAI } from './service';
import { SummaryKind } from './types';

export const aiKeys = {
  all: ['ai'] as const,
  summary: (kind: SummaryKind, ref_id: string) => [...aiKeys.all, 'summary', kind, ref_id] as const,
  search: (q: string, scope = 'tasks,pages,messages') =>
    [...aiKeys.all, 'search', q, scope] as const
};

export function summarizeQueryOptions(kind: SummaryKind, ref_id: string) {
  return queryOptions({
    queryKey: aiKeys.summary(kind, ref_id),
    queryFn: () => summarize({ kind, ref_id }),
    enabled: false
  });
}

export function aiSearchQueryOptions(q: string, scope = 'tasks,pages,messages') {
  return queryOptions({
    queryKey: aiKeys.search(q, scope),
    queryFn: () => searchAI(q, scope),
    enabled: q.trim().length > 0
  });
}
