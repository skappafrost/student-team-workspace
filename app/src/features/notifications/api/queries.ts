import { queryOptions } from '@tanstack/react-query';
import { getNotifications } from './service';

export const notificationKeys = {
  all: ['notifications'] as const,
  list: () => [...notificationKeys.all, 'list'] as const,
  detail: (id: string) => [...notificationKeys.all, 'detail', id] as const
};

export function notificationsQueryOptions() {
  return queryOptions({
    queryKey: notificationKeys.list(),
    queryFn: getNotifications
  });
}
