import { BackendNotification, Notification } from './types';
import { createApiClient } from '@/lib/api-client';

const apiRequest = createApiClient('/api/notifications');


const typeMap: Record<string, Notification['type']> = {
  info: 'info',
  success: 'success',
  warning: 'warning',
  danger: 'danger',
  'file-upload': 'success',
  mention: 'info',
  'task-assigned': 'info',
  'workspace-invite': 'success',
  message: 'info',
  other: 'info'
};

function mapNotification(n: BackendNotification): Notification {
  return {
    id: n.id,
    title: n.title,
    body: n.content ?? '',
    type: typeMap[n.type] ?? 'info',
    status: n.read ? 'read' : 'unread',
    createdAt: n.created_at
  };
}

export async function getNotifications(): Promise<Notification[]> {
  const data = await apiRequest<{ notifications: BackendNotification[] }>('');
  const notifications = data.notifications || [];
  return notifications.map(mapNotification);
}

export async function markNotificationAsRead(id: string): Promise<Notification> {
  const data = await apiRequest<{ notification: BackendNotification }>('', {
    method: 'PATCH',
    body: JSON.stringify({ id })
  });
  return mapNotification(data.notification);
}

export async function markAllNotificationsAsRead(): Promise<void> {
  await apiRequest<{ ok: boolean }>('', {
    method: 'POST',
    body: JSON.stringify({ action: 'mark-all-read' })
  });
}
