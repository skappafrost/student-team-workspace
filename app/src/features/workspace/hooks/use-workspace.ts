'use client';

import { useQuery } from '@tanstack/react-query';

import { ApiError } from '@/lib/api-client';

export interface Workspace {
  id: string;
  name: string;
}

interface WorkspaceResponse {
  workspace: Workspace;
}

/**
 * The status is the signal, so it is kept.
 *
 * `!res.ok` and a null body used to both become `null`, which is how a backend
 * blip turned into "this account has no workspace" — and `usePresence` answers a
 * null workspace by switching its query off (`enabled: !!workspaceId`) rather
 * than by reporting anything, so the two cases looked identical from here and
 * neither raised an error. They are separable at the BFF now
 * (`api/workspace/current/route.ts`): `404` is the account, `401`/`502`/`503`
 * are the lookup, and a caller can branch on `error.status` like the presence
 * hook already does for `403`.
 */
async function fetchWorkspace(): Promise<Workspace> {
  const res = await fetch('/api/workspace/current', { credentials: 'include' });
  const data = (await res.json().catch(() => null)) as
    | (Partial<WorkspaceResponse> & { error?: string })
    | null;
  if (!res.ok) {
    throw new ApiError(data?.error ?? `API error: ${res.status}`, res.status);
  }
  // A 200 without a workspace is not "no workspace" — the route says that with a
  // 404. Falling through to `undefined` here would instead fail inside
  // react-query, whose queryFn may not resolve to undefined.
  if (!data?.workspace) {
    throw new ApiError('Workspace lookup answered 200 with no workspace', 502);
  }
  return data.workspace;
}

export function workspaceQueryKey() {
  return ['workspace', 'current'];
}

export function useWorkspace() {
  return useQuery({
    queryKey: workspaceQueryKey(),
    queryFn: fetchWorkspace
  });
}
