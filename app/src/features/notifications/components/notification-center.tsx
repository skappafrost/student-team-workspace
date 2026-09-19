'use client';

// Source: GitHub/GitLab header notification bell idiom (badge + popover +
// mark-all). Catalog: design-references/notifications.md

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { NotificationCard } from '@/components/ui/notification-card';
import type { Notification } from '../api/types';
import {
  getNotifications,
  markNotificationAsRead,
  markAllNotificationsAsRead
} from '../api/service';
import { notificationKeys } from '../api/queries';

const MAX_VISIBLE = 5;

/**
 * Header notification bell. Backed by the real notifications API via React
 * Query (the previous zustand mock store is gone); optimistic read-state
 * updates keep the badge and list in sync with the notifications page.
 */
export function NotificationCenter() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: notificationKeys.list(),
    queryFn: getNotifications,
    refetchInterval: 60_000
  });
  const notifications = query.data ?? [];
  const count = notifications.filter((n) => n.status === 'unread').length;

  const setReadInCache = (id: string) =>
    queryClient.setQueryData<Notification[]>(notificationKeys.list(), (old) =>
      (old ?? []).map((n) => (n.id === id ? { ...n, status: 'read' as const } : n))
    );

  const readMutation = useMutation({
    mutationFn: (id: string) => markNotificationAsRead(id),
    onMutate: (id) => setReadInCache(id),
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to mark as read');
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    }
  });

  const markAllMutation = useMutation({
    mutationFn: markAllNotificationsAsRead,
    onMutate: () =>
      queryClient.setQueryData<Notification[]>(notificationKeys.list(), (old) =>
        (old ?? []).map((n) => ({ ...n, status: 'read' as const }))
      ),
    onSuccess: () => toast.success('All notifications marked as read'),
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to mark all as read');
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    }
  });

  return (
    <Popover>
      <PopoverTrigger render={<Button variant='ghost' size='icon' className='relative h-8 w-8' />}>
        <Icons.notification className='h-4 w-4' />
        {count > 0 && (
          <span className='bg-destructive text-destructive-foreground absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-medium'>
            {count > 9 ? '9+' : count}
          </span>
        )}
        <span className='sr-only'>Notifications</span>
      </PopoverTrigger>
      <PopoverContent align='end' className='w-[calc(100vw-2rem)] p-0 sm:w-[380px]' sideOffset={8}>
        <div className='flex items-center justify-between px-4 pt-3'>
          <Link href='/dashboard/notifications' className='group flex items-center gap-1'>
            <h4 className='text-sm font-semibold group-hover:underline'>Notifications</h4>
            <Icons.chevronRight className='text-muted-foreground h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5' />
          </Link>
          <div className='flex items-center gap-2'>
            {count > 0 && (
              <span className='bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-xs'>
                {count} new
              </span>
            )}
            {count > 0 && (
              <Button
                variant='ghost'
                size='sm'
                className='text-muted-foreground h-auto px-2 py-1 text-xs'
                onClick={() => markAllMutation.mutate()}
                disabled={markAllMutation.isPending}
              >
                Mark all as read
              </Button>
            )}
          </div>
        </div>
        <Separator />
        <ScrollArea className='h-[400px]'>
          {notifications.length === 0 ? (
            <Empty className='py-12'>
              <EmptyHeader>
                <EmptyMedia variant='icon'>
                  <Icons.notification />
                </EmptyMedia>
                <EmptyTitle>No notifications yet</EmptyTitle>
                <EmptyDescription>We will let you know when something happens.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className='flex flex-col gap-1 p-2'>
              {notifications.slice(0, MAX_VISIBLE).map((notification) => (
                <NotificationCard
                  key={notification.id}
                  id={notification.id}
                  title={notification.title}
                  body={notification.body}
                  status={notification.status}
                  createdAt={notification.createdAt}
                  actions={
                    notification.link
                      ? [{ id: 'open', label: 'Open', type: 'redirect' as const }]
                      : []
                  }
                  onMarkAsRead={(id) => readMutation.mutate(id)}
                  onAction={(notifId) => {
                    readMutation.mutate(notifId);
                    if (notification.link) router.push(notification.link);
                  }}
                />
              ))}
            </div>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
