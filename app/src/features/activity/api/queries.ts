import { queryOptions } from '@tanstack/react-query';
import { getActivity } from './service';

export const activityKeys = {
  all: ['activity'] as const
};

export const activityQueryOptions = () =>
  queryOptions({
    queryKey: activityKeys.all,
    queryFn: getActivity,
    staleTime: 30_000
  });
