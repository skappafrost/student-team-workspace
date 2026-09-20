'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react';

import { notificationKeys } from '@/features/notifications/api/queries';
import { useWorkspace } from '@/features/workspace/hooks/use-workspace';
import { ApiError } from '@/lib/api-client';
import { realtimeUrl, useRealtimeSocket } from '@/lib/realtime/use-websocket';

import { presenceKeys, presenceQueryOptions } from '../api/queries';
import { setMyPresence } from '../api/service';
import type { PresenceRow } from '../api/types';

/**
 * Keepalive period. The server's idle→away decay is 300s (`AWAY_AFTER_SECONDS`),
 * so 20s leaves fifteen retries inside the budget and still fits the ~1/min
 * throttling a background tab gets. It is also short enough for the browser spec
 * in `tests/presence-heartbeat.spec.ts` to observe a real tick.
 */
const PRESENCE_HEARTBEAT_MS = 20_000;

interface PresenceContextValue {
  byUser: ReadonlyMap<string, PresenceRow>;
  onlineCount: number;
  queryKey: readonly unknown[];
  isLoading: boolean;
  /** True for a guest: the server refuses presence entirely, so draw nothing. */
  hidden: boolean;
  report: (row: PresenceRow) => void;
}

const PresenceContext = createContext<PresenceContextValue | null>(null);

/**
 * One presence socket per browser tab, shared by every surface that draws a dot.
 *
 * `useRealtimeSocket` keys its effect on `url` and lives per hook instance, so a
 * hook-per-consumer would open one socket per component that renders a dot — four
 * here, and each one receiving every frame. The provider owns the socket and the
 * cache writes; consumers only read the Map.
 */
export function PresenceProvider({ children }: { children: ReactNode }) {
  const { data: workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? null;
  const queryClient = useQueryClient();
  // Memoised because `presenceKeys.workspace()` returns a fresh array, and an
  // unstable key here would rebuild the context value on every render and
  // re-render every consumer — the same defect that caused the kbar loop.
  const queryKey = useMemo(() => presenceKeys.workspace(workspaceId), [workspaceId]);
  const query = useQuery(presenceQueryOptions(workspaceId));
  const forbidden = query.error instanceof ApiError && query.error.status === 403;

  const report = useCallback(
    (row: PresenceRow) => {
      queryClient.setQueryData<PresenceRow[]>(queryKey, (old) => {
        const list = old ?? [];
        return [...list.filter((r) => r.user_id !== row.user_id), row];
      });
    },
    [queryClient, queryKey]
  );

  const { send } = useRealtimeSocket({
    // `workspace?.id` must not reach the URL as the literal "undefined": the
    // socket hook keys its effect on `url`, so a stable-but-wrong string would
    // open a connection that fails forever instead of waiting for the workspace.
    url: workspace && !forbidden ? realtimeUrl(`/ws/workspaces/${workspace.id}/presence`) : null,
    onMessage: (message) => {
      const frame = message as Partial<PresenceRow> & { type?: string };
      if (frame?.type === 'notification_created') {
        // This socket is the only one a dashboard tab holds, and the backend
        // joins it to the user's own room for exactly this frame. Only the fact
        // that something arrived is used: refetching keeps the server as the
        // source of truth for read/unread instead of merging a partial row.
        void queryClient.invalidateQueries({ queryKey: notificationKeys.all });
        return;
      }
      if (frame?.type !== 'presence_update' || !frame.user_id) return;
      // Applied straight into the cache rather than invalidated: the room
      // broadcast includes the acting user's own socket, so a busy workspace
      // would turn invalidate-per-frame into a refetch storm.
      report(frame as PresenceRow);
    },
    onOpen: () => {
      // Covers whatever changed while this socket was down.
      void queryClient.invalidateQueries({ queryKey });
    }
  });

  useEffect(() => {
    // The server derives `away` from a stale `last_seen` on a stored `online`
    // row, and this heartbeat is the only frame a tab nobody is typing in ever
    // sends: without it every dot greys out five minutes after the page opened,
    // socket and all. `send` is a no-op while the socket is not OPEN, so a tick
    // that lands mid-reconnect is simply skipped and the next one counts.
    const timer = window.setInterval(() => send({ type: 'ping' }), PRESENCE_HEARTBEAT_MS);
    return () => window.clearInterval(timer);
  }, [send]);

  const value = useMemo<PresenceContextValue>(() => {
    const rows = query.data ?? [];
    return {
      byUser: new Map(rows.map((row) => [row.user_id, row])),
      onlineCount: rows.filter((row) => row.status === 'online').length,
      queryKey,
      isLoading: query.isLoading,
      hidden: forbidden,
      report
    };
  }, [query.data, query.isLoading, forbidden, queryKey, report]);

  return <PresenceContext.Provider value={value}>{children}</PresenceContext.Provider>;
}

/**
 * Who is online in this workspace.
 *
 * Guests get `hidden: true` and callers draw nothing. The backend refuses guests
 * on presence read (`403`), write, and socket (`4403` before `accept()`), so a
 * dot for a guest would be invented rather than missing, and an error banner
 * would advertise a feature the reader cannot use.
 */
export function usePresence(): PresenceContextValue {
  const ctx = useContext(PresenceContext);
  if (!ctx) {
    throw new Error('usePresence must be used inside <PresenceProvider>');
  }
  return ctx;
}

/** Sets the caller's own status and settles the shared cache from the response. */
export function useSetPresence() {
  const { report } = usePresence();
  return useMutation({ mutationFn: setMyPresence, onSuccess: report });
}
