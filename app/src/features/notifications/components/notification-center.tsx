'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { NotificationCard } from '@/components/ui/notification-card';
import { notificationKeys, notificationsQueryOptions } from '../api/queries';
import { markAllNotificationsAsRead, markNotificationAsRead } from '../api/service';
import { inboxState } from '../lib/inbox-state';

const MAX_VISIBLE = 5;

/**
 * The header bell shows the inbox `GET /api/notifications` returns to the
 * notifications page — the same rows, the same mutations, one source.
 *
 * It used to read a store of invented rows and an action id -> route table that
 * sent `view`, `view-product` and `billing` all to `/dashboard/overview`, so the
 * badge counted rows nobody received and every button went to the same place.
 * Backend notifications carry a `link` and no `actions`, so the cards here render
 * no action row; clicking a notification through to its target is the
 * notifications page's existing behaviour (`notification-list.tsx`).
 */
export function NotificationCenter() {
  // Plain useQuery, not useSuspenseQuery: the header renders inside the server
  // component shell, where the relative '/api/notifications' URL cannot be
  // parsed — notification-list.tsx documents the same React #419 failure.
  const {
    data: notifications = [],
    isPending,
    isError,
    error,
    refetch
  } = useQuery(notificationsQueryOptions());
  const queryClient = useQueryClient();

  const markRead = useMutation({
    mutationFn: markNotificationAsRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to mark as read');
    }
  });

  const markAllRead = useMutation({
    mutationFn: markAllNotificationsAsRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to mark all as read');
    }
  });

  const count = notifications.filter((n) => n.status === 'unread').length;
  const state = inboxState({ isPending, isError, count: notifications.length });
  const visibleNotifications = notifications.slice(0, MAX_VISIBLE);

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
                onClick={() => markAllRead.mutate()}
                disabled={markAllRead.isPending}
              >
                Mark all as read
              </Button>
            )}
          </div>
        </div>
        <Separator />
        <ScrollArea className='h-[400px]'>
          {state === 'loading' && (
            <div className='text-muted-foreground text-sm'>Loading notifications…</div>
          )}
          {/* A refused fetch must not fall through to "no notifications yet",
              which is an empty inbox, not a broken one. Same branch, same order,
              as notification-list.tsx and file-list.tsx. */}
          {state === 'error' && (
            <Empty className='py-12'>
              <EmptyHeader>
                <EmptyMedia variant='icon' className='size-12 rounded-full'>
                  <Icons.warning className='size-6' />
                </EmptyMedia>
                <EmptyTitle>Failed to load notifications</EmptyTitle>
                <EmptyDescription>
                  {error instanceof Error ? error.message : 'Something went wrong.'}
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button variant='outline' size='sm' onClick={() => refetch()}>
                  Try again
                </Button>
              </EmptyContent>
            </Empty>
          )}
          {state === 'empty' && (
            <Empty className='py-12'>
              <EmptyHeader>
                <EmptyMedia variant='icon'>
                  <Icons.notification />
                </EmptyMedia>
                <EmptyTitle>No notifications yet</EmptyTitle>
                <EmptyDescription>We will let you know when something happens.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {state === 'list' && (
            <div className='flex flex-col gap-1 p-2'>
              {visibleNotifications.map((notification) => (
                <NotificationCard
                  key={notification.id}
                  id={notification.id}
                  title={notification.title}
                  body={notification.body}
                  status={notification.status}
                  createdAt={notification.createdAt}
                  actions={notification.actions}
                  onMarkAsRead={(id) => markRead.mutate(id)}
                />
              ))}
            </div>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
