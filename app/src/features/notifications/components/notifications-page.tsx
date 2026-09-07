'use client';

import { Suspense } from 'react';
import PageContainer from '@/components/layout/page-container';
import { NotificationList } from '@/features/notifications/components/notification-list';

export default function NotificationsPage() {
  return (
    <PageContainer
      pageTitle='Notifications'
      pageDescription='View and manage all your notifications.'
    >
      <Suspense
        fallback={
          <div className='flex flex-col gap-3'>
            <div className='bg-muted h-24 animate-pulse rounded-xl' />
            <div className='bg-muted h-24 animate-pulse rounded-xl' />
            <div className='bg-muted h-24 animate-pulse rounded-xl' />
          </div>
        }
      >
        <NotificationList />
      </Suspense>
    </PageContainer>
  );
}
