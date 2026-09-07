import { queryOptions } from '@tanstack/react-query';
import { getEvents } from './service';
import { EventFilters } from './types';

export const eventKeys = {
  all: ['events'] as const,
  list: (filters: EventFilters = {}) => [...eventKeys.all, 'list', filters] as const,
  detail: (id: string) => [...eventKeys.all, 'detail', id] as const
};

export function eventsQueryOptions(filters: EventFilters = {}) {
  return queryOptions({
    queryKey: eventKeys.list(filters),
    queryFn: () => getEvents(filters)
  });
}
