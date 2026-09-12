import { queryOptions } from '@tanstack/react-query';
import { getMyTasks } from './service';

export const deadlineKeys = {
  all: ['deadlines'] as const,
  mine: () => [...deadlineKeys.all, 'mine'] as const
};

export function myTasksQueryOptions() {
  return queryOptions({
    queryKey: deadlineKeys.mine(),
    queryFn: getMyTasks
  });
}
