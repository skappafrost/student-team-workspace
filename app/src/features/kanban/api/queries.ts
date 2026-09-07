import { queryOptions } from '@tanstack/react-query';
import { getTasks } from './service';

export const taskKeys = {
  all: ['tasks'] as const,
  list: (projectId: string) => [...taskKeys.all, 'list', projectId] as const,
  detail: (taskId: string) => [...taskKeys.all, 'detail', taskId] as const
};

export function tasksQueryOptions(projectId: string) {
  return queryOptions({
    queryKey: taskKeys.list(projectId),
    queryFn: () => getTasks(projectId)
  });
}
