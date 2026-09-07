import { queryOptions } from '@tanstack/react-query';
import { getChannels, getMessages } from './service';

export const channelKeys = {
  all: ['channels'] as const,
  list: () => [...channelKeys.all, 'list'] as const,
  detail: (id: string) => [...channelKeys.all, 'detail', id] as const,
  messages: (channelId: string | null) =>
    [...channelKeys.all, 'messages', channelId ?? 'none'] as const
};

export function channelsQueryOptions() {
  return queryOptions({
    queryKey: channelKeys.list(),
    queryFn: getChannels
  });
}

export function messagesQueryOptions(channelId: string | null) {
  return queryOptions({
    queryKey: channelKeys.messages(channelId),
    queryFn: () => {
      if (!channelId) return Promise.resolve([]);
      return getMessages(channelId);
    },
    enabled: !!channelId
  });
}
