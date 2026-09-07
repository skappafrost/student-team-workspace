'use client';

import { useQuery } from '@tanstack/react-query';

export interface Workspace {
  id: string;
  name: string;
}

interface WorkspaceResponse {
  workspace: Workspace | null;
}

async function fetchWorkspace(): Promise<Workspace | null> {
  const res = await fetch('/api/workspace/current', { credentials: 'include' });
  if (!res.ok) return null;
  const data = (await res.json()) as WorkspaceResponse;
  return data.workspace ?? null;
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
