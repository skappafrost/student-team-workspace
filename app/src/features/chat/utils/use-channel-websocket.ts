'use client';

import { useCallback, useMemo } from 'react';

import { isUuid, realtimeUrl, useRealtimeSocket } from '@/lib/realtime/use-websocket';

export interface UseChannelWebSocketOptions {
  channelId?: string;
  onMessage?: (message: unknown) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

/**
 * Chat socket for one channel. Transport lives in
 * `lib/realtime/use-websocket.ts`; this keeps the channel-specific id guard and
 * URL, plus the `sendTyping` name its callers use.
 *
 * `status` is surfaced so the channel view can say "reconnecting" instead of
 * rendering a stale list as if it were current.
 */
export function useChannelWebSocket({
  channelId,
  onMessage,
  onOpen,
  onClose
}: UseChannelWebSocketOptions) {
  const url = useMemo(
    () => (isUuid(channelId) ? realtimeUrl(`/ws/channels/${channelId}`) : null),
    [channelId]
  );

  const { send, status } = useRealtimeSocket({ url, onMessage, onOpen, onClose });

  // Stable on purpose: chat-page.tsx keeps `sendTyping` in a useCallback
  // dependency list, so a fresh closure per render would rebuild that callback
  // — and everything downstream of it — on every render.
  const sendTyping = useCallback(() => send({ type: 'typing' }), [send]);

  return { sendTyping, status };
}
