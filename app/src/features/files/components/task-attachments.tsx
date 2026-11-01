'use client';

import { useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { Separator } from '@/components/ui/separator';
import { linkedFilesQueryOptions, useDownloadFile, useUploadFile } from '../api/queries';
import { formatSize } from '../api/service';

// Source: composes this feature's file-uploader input pattern + file-list row layout.
export function TaskAttachments({ taskId }: { taskId: string }) {
  const { data: files } = useQuery(linkedFilesQueryOptions({ task_id: taskId }));
  const upload = useUploadFile();
  const download = useDownloadFile();
  const inputRef = useRef<HTMLInputElement>(null);

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // `mutate`, not `await mutateAsync`: the mutation reports through
    // onSuccess/onError (a toast on failure), and an awaited rejection here would
    // surface only as an unhandled promise rejection with the dialog left open.
    upload.mutate({ file, task_id: taskId });
    // Reset before returning, not after an await: on a rejected upload the reset
    // was skipped, so re-picking the same file fired nothing at all.
    e.target.value = '';
  };

  return (
    <div className='flex flex-col gap-2'>
      <div className='flex items-center justify-between'>
        <span className='text-sm font-medium'>Attachments</span>
        <Button
          type='button'
          variant='outline'
          size='sm'
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
        >
          <Icons.add className='mr-1.5 h-4 w-4' />
          {upload.isPending ? 'Uploading...' : 'Attach'}
        </Button>
        <input ref={inputRef} type='file' aria-label='Attach file' className='sr-only' onChange={onPick} />
      </div>
      <Separator />
      {(files ?? []).length === 0 ? (
        <p className='text-sm text-muted-foreground'>No files attached to this task.</p>
      ) : (
        <ul className='flex flex-col gap-1'>
          {(files ?? []).map((f) => (
            <li key={f.id} className='flex items-center justify-between gap-2 text-sm'>
              <span className='truncate'>{f.name}</span>
              <span className='flex items-center gap-2 text-muted-foreground'>
                <span className='text-xs'>{formatSize(f.size)}</span>
                <Button
                  type='button'
                  variant='ghost'
                  size='sm'
                  onClick={() => download.mutate(f)}
                  aria-label={`Download ${f.name}`}
                >
                  <Icons.download className='h-4 w-4' />
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
