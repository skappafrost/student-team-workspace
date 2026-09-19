'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import { useWorkspace } from '@/features/workspace/hooks/use-workspace';
import { ApiError } from '@/lib/api-client';
import { realtimeUrl, useRealtimeSocket } from '@/lib/realtime/use-websocket';

import { presenceKeys, presenceQueryOptions } from '../api/queries';
import { setMyPresence } from '../api/service';
import type { PresenceRow, PresenceUpdateFrame } from '../api/types';

/**
 * Who is online in this workspace, kept current by the presence socket.
 *
 * `hidden` is the guest answer. The backend refuses guests on presence read
 * (`403`), write, and socket (`4403` before `accept()`), so a guest has no
 * presence surface at all — and a dot rendered from an absent payload would be
 * a fabrication rather than a missing value. Callers drop the indicator entirely
 * instead of showing "unknown": an error banner would advertise a feature the
 * reader cannot use.
 */
export function usePresenceMap() {
  const { data: workspace } = useWorkspace();
  const queryClient = useQueryClient();
  const queryKey = presenceKeys.workspace(workspace?.id ?? null);
  const query = useQuery(presenceQueryOptions(workspace?.id ?? null));
  const forbidden = query.error instanceof ApiError && query.error.status === 403;

  useRealtimeSocket({
    // `workspace?.id` must not reach the URL as the literal "undefined": the
    // hook keys its effect on `url`, so a wrong-but-stable string would open a
    // socket that 404s forever instead of simply waiting for the workspace.
    url:
      workspace && !forbidden
        ? realtimeUrl(`/ws/workspaces/${workspace.id}/presence`)
        : null,
    onMessage: (message) => {
      const frame = message as PresenceUpdateFrame;
      if (frame?.type !== 'presence_update' || !frame.user_id) return;
      // Applied straight into the cache rather than invalidated: the room
      // broadcast includes the acting user's own socket, so a busy workspace
      // would turn invalidate-on-every-frame into a refetch storm.
      queryClient.setQueryData<PresenceRow[]>(queryKey, (old) => {
        const list = old ?? [];
        return [...list.filter((row) => row.user_id !== frame.user_id), frame];
      });
    },
    onOpen: () => {
      // Covers whatever changed while this socket was down.
      void queryClient.invalidateQueries({ queryKey });
    }
  });

  // Memoised so consumers can hold the Map identity across unrelated renders.
  const byUser = useMemo(
    () => new Map((query.data ?? []).map((row) => [row.user_id, row])),
    [query.data]
  );

  return {
    byUser,
    queryKey,
    isLoading: query.isLoading,
    hidden: forbidden
  };
}

/** Sets the caller's own status and settles the cache from the response. */
export function useSetPresence() {
  const { data: workspace } = useWorkspace();
  const queryClient = useQueryClient();
  const queryKey = presenceKeys.workspace(workspace?.id ?? null);

  return useMutation({
    mutationFn: setMyPresence,
    onSuccess: (row) => {
      queryClient.setQueryData<PresenceRow[]>(queryKey, (old) => {
        const list = old ?? [];
        return [...list.filter((r) => r.user_id !== row.user_id), row];
      });
    }
  });
}
