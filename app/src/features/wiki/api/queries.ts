import { queryOptions } from '@tanstack/react-query';
import { getPage, getPageHistory, getPages, searchPages } from './service';

export const wikiKeys = {
  all: ['wiki'] as const,
  list: () => [...wikiKeys.all, 'list'] as const,
  search: (q: string) => [...wikiKeys.all, 'search', q] as const,
  recent: () => [...wikiKeys.all, 'recent'] as const,
  detail: (id: string | null) => [...wikiKeys.all, 'detail', id ?? 'none'] as const
};

export function pagesQueryOptions() {
  return queryOptions({
    queryKey: wikiKeys.list(),
    queryFn: getPages
  });
}

export function searchPagesQueryOptions(q: string) {
  return queryOptions({
    queryKey: wikiKeys.search(q),
    queryFn: () => searchPages(q),
    enabled: q.trim().length > 0
  });
}

export function recentPagesQueryOptions() {
  return queryOptions({
    queryKey: wikiKeys.recent(),
    queryFn: () => searchPages('', true)
  });
}

export function pageQueryOptions(id: string | null) {
  return queryOptions({
    queryKey: wikiKeys.detail(id),
    queryFn: () => (id ? getPage(id) : Promise.resolve(null)),
    enabled: !!id
  });
}

export function pageHistoryQueryOptions(id: string | null) {
  return queryOptions({
    queryKey: [...wikiKeys.detail(id), 'history'] as const,
    queryFn: () => (id ? getPageHistory(id) : Promise.resolve([])),
    enabled: !!id
  });
}
