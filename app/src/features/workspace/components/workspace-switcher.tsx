'use client';

// Source: Slack/Discord workspace-switcher idiom — sidebar header dropdown
// listing joined workspaces; switching reloads so every BFF-scoped surface
// (channels, tasks, files, pages) re-resolves against the new workspace.

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Icons } from '@/components/icons';

interface WorkspaceItem {
  id: string;
  name?: string;
}

async function fetchWorkspaces(): Promise<WorkspaceItem[]> {
  const res = await fetch('/api/workspaces', { credentials: 'include' });
  if (!res.ok) return [];
  const data = (await res.json().catch(() => ({}))) as { workspaces?: WorkspaceItem[] };
  return data.workspaces ?? [];
}

async function fetchCurrent(): Promise<WorkspaceItem | null> {
  const res = await fetch('/api/workspace/current', { credentials: 'include' });
  if (!res.ok) return null;
  const data = (await res.json().catch(() => ({}))) as { workspace?: WorkspaceItem | null };
  return data.workspace ?? null;
}

export function WorkspaceSwitcher() {
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);

  const workspacesQuery = useQuery({ queryKey: ['workspaces'], queryFn: fetchWorkspaces });
  const currentQuery = useQuery({ queryKey: ['workspace', 'current'], queryFn: fetchCurrent });

  const workspaces = workspacesQuery.data ?? [];
  const current = currentQuery.data;

  const switchTo = async (workspace: WorkspaceItem) => {
    if (workspace.id === current?.id) {
      setOpen(false);
      return;
    }
    setSwitching(true);
    try {
      const res = await fetch('/api/workspace/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspace.id }),
        credentials: 'include'
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(data.error || `Switch failed: ${res.status}`);
      }
      // Full reload: every BFF route resolves the workspace cookie server-side.
      window.location.reload();
    } catch (err) {
      setSwitching(false);
      toast.error(err instanceof Error ? err.message : 'Failed to switch workspace');
    }
  };

  if (workspaces.length === 0) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant='outline'
            className='w-full justify-between gap-2 px-3'
            disabled={switching}
            aria-label='Switch workspace'
          />
        }
      >
        <span className='truncate text-sm font-medium'>{current?.name ?? 'Workspace'}</span>
        <Icons.chevronsUpDown className='text-muted-foreground size-4 shrink-0' />
      </PopoverTrigger>
      <PopoverContent align='start' className='w-56 p-1'>
        {workspaces.map((workspace) => (
          <button
            key={workspace.id}
            type='button'
            onClick={() => switchTo(workspace)}
            disabled={switching}
            aria-current={workspace.id === current?.id ? 'true' : undefined}
            className='hover:bg-muted flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors'
          >
            <span className='truncate'>{workspace.name ?? 'Workspace'}</span>
            {workspace.id === current?.id && (
              <Icons.check className='text-primary size-4 shrink-0' aria-hidden='true' />
            )}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
