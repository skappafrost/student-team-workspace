import {
  Channel,
  DMChannel,
  Message,
  CreateChannelPayload,
  CreateMessagePayload,
  ReactionSummary,
  WorkspaceMember
} from './types';
import { createApiClient } from '@/lib/api-client';

const apiRequest = createApiClient('/api/channels');

export async function getChannels(): Promise<Channel[]> {
  const data = await apiRequest<{ channels: Channel[] }>('');
  return data.channels || [];
}

export async function createChannel(payload: CreateChannelPayload): Promise<Channel> {
  const data = await apiRequest<{ channel: Channel }>('', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  return data.channel;
}

/** Page size the chat history is opened with, and the unit of "load earlier".
 *
 * The backend's default is its 1000 cap, which in a busy channel means the first
 * response is the 1000 *oldest* messages. Asking for a bounded window from the
 * newest end is what makes the newest messages appear at all.
 */
export const MESSAGES_PAGE_SIZE = 50;

export interface MessagePageOptions {
  q?: string;
  limit?: number;
  /** A message id: return the window strictly older than it. */
  before?: string;
}

export async function getMessages(
  channelId: string,
  options: MessagePageOptions = {}
): Promise<Message[]> {
  const params = new URLSearchParams();
  if (options.q?.trim()) params.set('q', options.q.trim());
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  if (options.before) params.set('before', options.before);
  const suffix = params.size > 0 ? `?${params.toString()}` : '';
  const data = await apiRequest<{ messages: Message[] }>(
    `/${encodeURIComponent(channelId)}/messages${suffix}`
  );
  return data.messages || [];
}


export async function sendMessage(
  channelId: string,
  payload: CreateMessagePayload
): Promise<Message> {
  const data = await apiRequest<{ message: Message }>(
    `/${encodeURIComponent(channelId)}/messages`,
    {
      method: 'POST',
      body: JSON.stringify(payload)
    }
  );
  return data.message;
}

export async function getDMs(): Promise<DMChannel[]> {
  const res = await fetch('/api/dms', { credentials: 'include' });
  const data = (await res.json().catch(() => ({}))) as { dms?: DMChannel[] };
  if (!res.ok) return [];
  return data.dms ?? [];
}

export async function createDM(userId: string): Promise<DMChannel> {
  const res = await fetch('/api/dms', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId }),
    credentials: 'include'
  });
  const data = (await res.json().catch(() => ({}))) as {
    dm?: DMChannel;
    error?: string;
  };
  if (!res.ok || !data.dm) {
    throw new Error(data.error || `API error: ${res.status}`);
  }
  return data.dm;
}

export async function getMembers(): Promise<WorkspaceMember[]> {
  const res = await fetch('/api/workspace/members', { credentials: 'include' });
  const data = (await res.json().catch(() => ({}))) as { members?: WorkspaceMember[] };
  if (!res.ok) return [];
  return data.members ?? [];
}

export async function toggleReaction(
  messageId: string,
  emoji: string
): Promise<ReactionSummary[]> {
  const res = await fetch(`/api/messages/${encodeURIComponent(messageId)}/reactions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ emoji }),
    credentials: 'include'
  });
  const data = (await res.json().catch(() => ({}))) as {
    reactions?: ReactionSummary[];
    error?: string;
  };
  if (!res.ok) {
    throw new Error(data.error || `API error: ${res.status}`);
  }
  return data.reactions ?? [];
}

export async function createMessage(
  channelId: string,
  payload: CreateMessagePayload
): Promise<Message> {
  return sendMessage(channelId, payload);
}
