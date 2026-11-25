'use client';

import { useQuery } from '@tanstack/react-query';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import { Icons } from '@/components/icons';
import { LoadingButton } from '@/components/ui/loading-button';
import { FileRecord } from '../api/types';
import { formatSize } from '../api/service';
import { filesQueryOptions, useDeleteFile, useDownloadFile } from '../api/queries';
import { ShareFileDialog } from './share-file-dialog';

function formatDate(iso: string) {
  return new Date(iso).toLocaleString();
}

export function FileList() {
  // Plain useQuery (not suspense): useSuspenseQuery errors server-side on the
  // relative '/api/files' fetch, which breaks the streamed boundary (React
  // #419) and leaves the page stuck on the loading fallback.
  const { data: files = [], isPending, isError, error, refetch } = useQuery(filesQueryOptions());
  const remove = useDeleteFile();
  const download = useDownloadFile();

  if (isPending) {
    return <div className='text-muted-foreground text-sm'>Loading files…</div>;
  }

  if (isError) {
    return (
      <Empty className='border py-16'>
        <EmptyHeader>
          <EmptyMedia variant='icon' className='size-12 rounded-full'>
            <Icons.warning className='size-6' />
          </EmptyMedia>
          <EmptyTitle>Failed to load files</EmptyTitle>
          <EmptyDescription>
            {error instanceof Error ? error.message : 'Something went wrong.'}
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant='outline' size='sm' onClick={() => refetch()}>
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Size</TableHead>
          <TableHead>Uploaded at</TableHead>
          <TableHead className='text-right'>Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {files.length === 0 && (
          <TableRow>
            <TableCell colSpan={4}>
              <Empty className='py-10'>
                <EmptyHeader>
                  <EmptyMedia variant='icon'>
                    <Icons.upload />
                  </EmptyMedia>
                  <EmptyTitle>No files uploaded yet</EmptyTitle>
                  <EmptyDescription>Upload a file to share it with the workspace.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            </TableCell>
          </TableRow>
        )}
        {files.map((file: FileRecord) => (
          <TableRow key={file.id}>
            <TableCell className='font-medium'>{file.name}</TableCell>
            <TableCell>{formatSize(file.size)}</TableCell>
            <TableCell>{formatDate(file.created_at)}</TableCell>
            <TableCell className='text-right'>
              <div className='flex justify-end gap-2'>
                <ShareFileDialog file={file} />
                <LoadingButton
                  variant='outline'
                  size='sm'
                  loading={download.isPending}
                  onClick={() => download.mutate(file)}
                >
                  <Icons.download className='mr-1.5 h-4 w-4' />
                  Download
                </LoadingButton>
                <Button
                  variant='destructive'
                  size='sm'
                  onClick={() => remove.mutate(file.id)}
                  disabled={remove.isPending}
                >
                  <Icons.trash className='mr-1.5 h-4 w-4' />
                  Delete
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
