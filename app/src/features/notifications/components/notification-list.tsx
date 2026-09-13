'use client';

import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useCallback } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { notificationKeys, notificationsQueryOptions } from '../api/queries';
import { markAllNotificationsAsRead, markNotificationAsRead } from '../api/service';
import { Notification as NotificationType, NotificationStatus } from '../api/types';

const formatDate = (date: string | Date): string => {
  const d = new Date(date);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};

const badgeVariantByType: Record<
  NotificationType['type'],
  'default' | 'secondary' | 'destructive' | 'warning'
> = {
  info: 'secondary',
  success: 'default',
  warning: 'warning',
  danger: 'destructive'
};

interface NotificationListProps {
  filter?: NotificationStatus | 'all';
}

export function NotificationList({ filter = 'all' }: NotificationListProps) {
  const { data: notifications = [] } = useSuspenseQuery(notificationsQueryOptions());
  const queryClient = useQueryClient();
  const router = useRouter();

  const markReadMutation = useMutation({
    mutationFn: markNotificationAsRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
      toast.success('Marked as read');
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to mark as read');
    }
  });

  const markAllReadMutation = useMutation({
    mutationFn: markAllNotificationsAsRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
      toast.success('All notifications marked as read');
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to mark all as read');
    }
  });

  const handleMarkAsRead = useCallback(
    (id: string) => {
      markReadMutation.mutate(id);
    },
    [markReadMutation]
  );

  const handleMarkAllAsRead = useCallback(() => {
    markAllReadMutation.mutate();
  }, [markAllReadMutation]);

  const visibleNotifications =
    filter === 'all' ? notifications : notifications.filter((n) => n.status === filter);

  const unreadCount = notifications.filter((n) => n.status === 'unread').length;

  if (notifications.length === 0) {
    return (
      <div className='flex flex-col items-center justify-center py-16'>
        <Icons.notification className='text-muted-foreground/40 mb-3 h-10 w-10' />
        <p className='text-muted-foreground text-sm'>No notifications</p>
      </div>
    );
  }

  return (
    <div className='space-y-4'>
      <div className='flex items-center justify-between'>
        <p className='text-muted-foreground text-sm'>
          {unreadCount > 0 ? `${unreadCount} unread` : 'All caught up'}
        </p>
        {unreadCount > 0 && (
          <Button
            variant='outline'
            size='sm'
            onClick={handleMarkAllAsRead}
            disabled={markAllReadMutation.isPending}
          >
            {markAllReadMutation.isPending ? (
              <Icons.spinner className='mr-2 h-4 w-4 animate-spin' />
            ) : null}
            Mark all as read
          </Button>
        )}
      </div>
      <div className='flex flex-col gap-3'>
        {visibleNotifications.map((notification) => (
          <Card
            key={notification.id}
            role={notification.link ? 'link' : undefined}
            tabIndex={notification.link ? 0 : undefined}
            onClick={() => {
              if (notification.status === 'unread') handleMarkAsRead(notification.id);
              if (notification.link) router.push(notification.link);
            }}
            onKeyDown={(e) => {
              if (notification.link && (e.key === 'Enter' || e.key === ' ')) {
                e.preventDefault();
                if (notification.status === 'unread') handleMarkAsRead(notification.id);
                router.push(notification.link);
              }
            }}
            className={`${
              notification.status === 'unread' ? 'border-l-4 border-l-sky-500 bg-muted/40' : ''
            } ${notification.link ? 'hover:bg-accent/50 cursor-pointer transition-colors' : ''}`}
          >
            <CardContent className='p-4'>
              <div className='flex items-start justify-between gap-4'>
                <div className='min-w-0 flex-1 space-y-1'>
                  <div className='flex items-center gap-2'>
                    <h3
                      className={
                        notification.status === 'unread'
                          ? 'text-foreground font-semibold'
                          : 'text-muted-foreground font-medium'
                      }
                    >
                      {notification.title}
                    </h3>
                    <Badge variant={badgeVariantByType[notification.type]}>
                      {notification.type}
                    </Badge>
                  </div>
                  <p className='text-muted-foreground text-sm'>{notification.body}</p>
                  <p className='text-muted-foreground/60 text-xs'>
                    {formatDate(notification.createdAt)}
                  </p>
                </div>
                {notification.status === 'unread' && (
                  <Button
                    variant='ghost'
                    size='icon'
                    className='h-8 w-8 shrink-0'
                    onClick={(e) => {
                      e.stopPropagation();
                      handleMarkAsRead(notification.id);
                    }}
                    disabled={markReadMutation.isPending}
                    aria-label='Mark as read'
                  >
                    {markReadMutation.isPending ? (
                      <Icons.spinner className='h-4 w-4 animate-spin' />
                    ) : (
                      <Icons.check className='h-4 w-4' />
                    )}
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
