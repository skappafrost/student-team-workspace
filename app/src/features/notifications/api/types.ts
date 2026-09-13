import type { components } from '@/types/api';

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
  actions?: NotificationAction[];
}

/**
 * Generated source of truth for a backend notification
 * (`components['schemas']['NotificationOut']` in `@/types/api`, emitted by
 * `bun run gen:api`). Re-exported here so the pilot feature reads the
 * backend contract from the generated file instead of hand-maintaining it.
 */
export type GeneratedNotificationOut =
  components['schemas']['NotificationOut'];

/**
 * SHAPE MISMATCH (kept manual on purpose — do not force-fit):
 * generated `NotificationOut.content` is a REQUIRED `string | null` key
 * (backend `NotificationOut.content: Optional[str]` has no default, so the
 * key is always present and may be null), while this hand-written type
 * declares it as OPTIONAL `content?: string` (key may be absent, never
 * null). `service.ts` maps with `n.content ?? ''`, which is safe for both
 * `undefined` and `null`, so runtime behavior is unchanged.
 */
export interface BackendNotification {
  id: string;
  user_id: string;
  type: string;
  title: string;
  content?: string;
  read: boolean;
  created_at: string;
}

export interface MarkAsReadPayload {
  id: string;
}
