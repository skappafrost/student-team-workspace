'use client';

/**
 * Wiki page version history sheet (F09)
 *
 * Sources (zero-native-design rule):
 * - Side panel: shadcn/ui Sheet (https://ui.shadcn.com/docs/components/sheet)
 * - Buttons: shadcn/ui Button
 * - Query/mutation: TanStack Query
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger
} from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { pageHistoryQueryOptions, wikiKeys } from '../api/queries';
import { restorePageVersion } from '../api/service';
import type { WikiPage, WikiPageVersion } from '../api/types';

export function PageHistorySheet({ page }: { page: WikiPage }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<WikiPageVersion | null>(null);
  const queryClient = useQueryClient();

  const historyQuery = useQuery({
    ...pageHistoryQueryOptions(open ? page.id : null)
  });
  const versions = historyQuery.data ?? [];

  const restore = useMutation({
    mutationFn: (version: number) => restorePageVersion(page.id, version),
    onSuccess: () => {
      toast.success('Version restored');
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: wikiKeys.detail(page.id) });
      queryClient.invalidateQueries({ queryKey: wikiKeys.list() });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to restore');
    }
  });

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={
          <Button variant='outline' size='sm'>
            History
          </Button>
        }
      />
      <SheetContent className='flex w-full flex-col sm:max-w-lg'>
        <SheetHeader>
          <SheetTitle>Version history</SheetTitle>
          <SheetDescription>
            {versions.length} version{versions.length === 1 ? '' : 's'} of “{page.title}”
          </SheetDescription>
        </SheetHeader>

        {historyQuery.isLoading ? (
          <div className='flex flex-col gap-2 px-4'>
            <Skeleton className='h-10 w-full' />
            <Skeleton className='h-10 w-full' />
            <Skeleton className='h-10 w-full' />
          </div>
        ) : versions.length === 0 ? (
          <p className='text-muted-foreground px-4 text-sm'>No history yet.</p>
        ) : (
          <div className='flex min-h-0 flex-1 gap-3 px-4 pb-4'>
            <ul className='divide-border w-40 shrink-0 divide-y overflow-y-auto rounded-md border'>
              {versions.map((v) => (
                <li key={v.id}>
                  <button
                    type='button'
                    onClick={() => setSelected(v)}
                    className={`w-full px-3 py-2 text-left text-xs hover:bg-muted ${
                      selected?.id === v.id ? 'bg-muted font-medium' : ''
                    }`}
                  >
                    <div>v{v.version}</div>
                    <div className='text-muted-foreground truncate'>
                      {v.author_name ?? 'Unknown'}
                    </div>
                    <div className='text-muted-foreground'>
                      {new Date(v.created_at).toLocaleDateString()}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            <div className='flex min-h-0 flex-1 flex-col gap-2'>
              {selected ? (
                <>
                  <div className='text-sm font-medium'>{selected.title}</div>
                  <div className='bg-muted/40 min-h-0 flex-1 overflow-y-auto rounded-md border p-3'>
                    <pre className='text-xs whitespace-pre-wrap'>
                      {selected.content || '(empty)'}
                    </pre>
                  </div>
                  <Button
                    size='sm'
                    disabled={restore.isPending}
                    onClick={() => restore.mutate(selected.version)}
                  >
                    {restore.isPending ? 'Restoring…' : `Restore v${selected.version}`}
                  </Button>
                </>
              ) : (
                <p className='text-muted-foreground text-sm'>
                  Select a version to preview it.
                </p>
              )}
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
