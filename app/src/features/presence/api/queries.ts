import { queryOptions } from '@tanstack/react-query';

import { getWorkspacePresence } from './service';

export const presenceKeys = {
  all: ['presence'] as const,
  workspace: (workspaceId: string | null) =>
    [...presenceKeys.all, workspaceId ?? 'none'] as const
};

/**
 * `staleTime` is short and there is no `refetchInterval`: the workspace presence
 * room pushes every change, so polling would only add requests. What the socket
 * cannot cover is the time it was down, which is why the hook refetches on open.
 */
export const presenceQueryOptions = (workspaceId: string | null) =>
  queryOptions({
    queryKey: presenceKeys.workspace(workspaceId),
    queryFn: getWorkspacePresence,
    enabled: !!workspaceId,
    staleTime: 30_000
  });
