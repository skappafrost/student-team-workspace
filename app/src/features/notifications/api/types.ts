export type NotificationType = 'info' | 'success' | 'warning' | 'danger';
export type NotificationStatus = 'unread' | 'read' | 'archived';

export interface NotificationAction {
  id: string;
  label: string;
  type: 'redirect' | 'api_call' | 'workflow' | 'modal';
  style?: 'primary' | 'danger' | 'default';
}

export interface Notification {
  id: string;
  title: string;
  body: string;
  type: NotificationType;
  status: NotificationStatus;
  createdAt: string;
  link?: string | null;
  actions?: NotificationAction[];
}

export interface BackendNotification {
  id: string;
  user_id: string;
  type: string;
  title: string;
  content?: string;
  link?: string | null;
  read: boolean;
  created_at: string;
}

export interface MarkAsReadPayload {
  id: string;
}
