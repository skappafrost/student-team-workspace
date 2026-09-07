'use client';

import { useEffect, useRef } from 'react';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isValidChannelId(id: string | undefined): id is string {
  return !!id && UUID_RE.test(id);
}

function getApiBaseUrl(): string {
  if (typeof window === 'undefined') return '';
  return process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ?? 'http://127.0.0.1:8000';
}

function getWsUrl(channelId: string): string {
  const base = getApiBaseUrl();
  const wsBase = base.replace(/^http/, 'ws');
  const url = new URL(`/ws/channels/${channelId}`, wsBase);
  return url.toString();
}

export interface UseChannelWebSocketOptions {
  channelId?: string;
  onMessage?: (message: unknown) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

export function useChannelWebSocket({
  channelId,
  onMessage,
  onOpen,
  onClose
}: UseChannelWebSocketOptions) {
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectDelayRef = useRef<number>(1000);

  useEffect(() => {
    if (!isValidChannelId(channelId)) {
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;

      const url = getWsUrl(channelId as string);
      try {
        const socket = new WebSocket(url);
        socketRef.current = socket;

        socket.addEventListener('open', () => {
          reconnectDelayRef.current = 1000;
          onOpen?.();
        });

        socket.addEventListener('message', (event) => {
          try {
            const data = JSON.parse(event.data);
            onMessage?.(data);
          } catch {
            // Ignore malformed payloads.
          }
        });

        socket.addEventListener('close', () => {
          onClose?.();
          if (!cancelled) {
            scheduleReconnect();
          }
        });

        socket.addEventListener('error', () => {
          // Errors are followed by a close event; reconnect there.
        });
      } catch {
        scheduleReconnect();
      }
    }

    function scheduleReconnect() {
      if (cancelled) return;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectDelayRef.current = Math.min(reconnectDelayRef.current * 2, 5000);
        connect();
      }, reconnectDelayRef.current);
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [channelId, onMessage, onOpen, onClose]);
}
