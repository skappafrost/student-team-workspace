'use client';

import { useCallback, useEffect, useRef } from 'react';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 5000;

export function isUuid(id: string | undefined): id is string {
  return !!id && UUID_RE.test(id);
}

export function getApiBaseUrl(): string {
  if (typeof window === 'undefined') return '';
  // Derive the host from the page instead of defaulting to 127.0.0.1: this
  // file's own guard below refuses to connect when the socket host differs from
  // the page host, so a literal default here would contradict it. The 26 BFF
  // route handlers keep their 127.0.0.1 default — they are server-to-server and
  // forward the cookie by hand, where the host does not gate authentication.
  return (
    process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ??
    `${window.location.protocol}//${window.location.hostname}:8000`
  );
}

/**
 * Absolute `ws(s)://` URL for a backend socket path, or null when there is no
 * browser yet to open one from.
 */
export function realtimeUrl(path: string): string | null {
  const base = getApiBaseUrl();
  if (!base) return null;
  return new URL(path, base.replace(/^http/, 'ws')).toString();
}

/**
 * The browser opens these sockets itself, so authentication is the
 * `session_token` cookie — which is `SameSite=Lax` and host-scoped. Serving the
 * app on `localhost` while pointing the socket at `127.0.0.1` (different
 * hostnames, same machine) means the cookie is never attached and every
 * handshake is rejected with 4401 *before* `accept()`. That reads to a
 * developer as "realtime is broken" with nothing in the console, which is why
 * it says so loudly here instead of reconnecting quietly forever.
 *
 * Ports are excluded on purpose: LAN setups run both apps on one host with
 * different ports and work fine.
 */
function cookieWillReach(url: string): boolean {
  if (typeof window === 'undefined') return true;
  try {
    return new URL(url).hostname === window.location.hostname;
  } catch {
    return true;
  }
}

export interface UseRealtimeSocketOptions {
  /** Full `ws://` URL, or null to stay disconnected. */
  url: string | null | undefined;
  onMessage?: (message: unknown) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

/**
 * One reconnecting WebSocket for `url`, shared by every caller that reads the
 * same URL.
 *
 * Callbacks are held in a ref rather than in the effect's dependency list:
 * callers pass inline arrows, so depending on their identity tore the socket
 * down and rebuilt it on every parent render.
 */
export function useRealtimeSocket({ url, onMessage, onOpen, onClose }: UseRealtimeSocketOptions) {
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const delayRef = useRef<number>(RECONNECT_MIN_MS);
  const handlersRef = useRef({ onMessage, onOpen, onClose });

  useEffect(() => {
    handlersRef.current = { onMessage, onOpen, onClose };
  });

  useEffect(() => {
    if (!url) return;

    if (!cookieWillReach(url)) {
      const host = typeof window !== 'undefined' ? window.location.hostname : '?';
      console.error(
        `[stw-realtime] not connecting to ${url}: the page is served from ` +
          `'${host}', so the session_token cookie will not be attached and the ` +
          'handshake would be rejected. Set NEXT_PUBLIC_API_URL to the same ' +
          'hostname as the app (localhost, not 127.0.0.1) — see CONTRIBUTING.md.'
      );
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;
      try {
        const socket = new WebSocket(url as string);
        socketRef.current = socket;

        socket.addEventListener('open', () => {
          delayRef.current = RECONNECT_MIN_MS;
          handlersRef.current.onOpen?.();
        });

        socket.addEventListener('message', (event) => {
          try {
            const data = JSON.parse(event.data);
            handlersRef.current.onMessage?.(data);
          } catch {
            // Ignore malformed payloads.
          }
        });

        socket.addEventListener('close', () => {
          handlersRef.current.onClose?.();
          if (!cancelled) scheduleReconnect();
        });

        socket.addEventListener('error', () => {
          // Errors are always followed by a close event; reconnect there.
        });
      } catch {
        scheduleReconnect();
      }
    }

    function scheduleReconnect() {
      if (cancelled) return;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => {
        delayRef.current = Math.min(delayRef.current * 2, RECONNECT_MAX_MS);
        connect();
      }, delayRef.current);
    }

    connect();

    return () => {
      cancelled = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, [url]);

  const send = useCallback((frame: unknown) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(frame));
    }
  }, []);

  return { send, socketRef };
}
