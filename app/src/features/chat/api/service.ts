import {
  Channel,
  DMChannel,
  Message,
  CreateChannelPayload,
  CreateMessagePayload,
  ReactionSummary,
  WorkspaceMember
} from './types';

async function apiRequest<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api/channels${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string>)
    },
    credentials: 'include'
  });

  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) {
    throw new Error(data.error || `API error: ${res.status}`);
  }
  return data;
}

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

export async function getMessages(channelId: string, q?: string): Promise<Message[]> {
  const query = q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : '';
  const data = await apiRequest<{ messages: Message[] }>(
    `/${encodeURIComponent(channelId)}/messages${query}`
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
