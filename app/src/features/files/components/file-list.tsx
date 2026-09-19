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
import { FileRecord } from '../api/types';
import { formatSize, downloadFile } from '../api/service';
import { filesQueryOptions, useDeleteFile } from '../api/queries';
import { ShareFileDialog } from './share-file-dialog';
import { useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';

function formatDate(iso: string) {
  return new Date(iso).toLocaleString();
}

function isImage(file: FileRecord) {
  return file.type?.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg)$/i.test(file.name);
}

// Source: shadcn/ui Dialog; blob object-URL preview idiom.
function PreviewButton({ file }: { file: FileRecord }) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const open = async () => {
    setLoading(true);
    try {
      // file.url points at the API origin; fetch via the BFF content proxy.
      const res = await fetch(`/api/files/${encodeURIComponent(file.id)}/content`, {
        credentials: 'include'
      });
      if (!res.ok) throw new Error(`Preview failed: ${res.status}`);
      const blob = await res.blob();
      setUrl(window.URL.createObjectURL(blob));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Preview failed');
    } finally {
      setLoading(false);
    }
  };

  const close = () => {
    if (url) window.URL.revokeObjectURL(url);
    setUrl(null);
  };

  return (
    <>
      <Button variant='outline' size='sm' onClick={open} disabled={loading}>
        <Icons.eye className='mr-1.5 h-4 w-4' />
        Preview
      </Button>
      <Dialog open={!!url} onOpenChange={(open) => !open && close()}>
        <DialogContent className='sm:max-w-2xl'>
          <DialogHeader>
            <DialogTitle className='truncate text-sm'>{file.name}</DialogTitle>
          </DialogHeader>
          {url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={url}
              alt={`Preview of ${file.name}`}
              className='max-h-[70vh] w-full rounded-xl object-contain'
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

export function FileList() {
  // Plain useQuery (not suspense): useSuspenseQuery errors server-side on the
  // relative '/api/files' fetch, which breaks the streamed boundary (React
  // #419) and leaves the page stuck on the loading fallback.
  const { data: files = [], isPending, isError, error, refetch } = useQuery(filesQueryOptions());
  const remove = useDeleteFile();

  // Windowing: above the threshold only the visible rows mount. Table rows
  // are fixed-height, so a simple virtualizer with spacer rows works.
  const VIRTUALIZE_THRESHOLD = 15;
  const ROW_HEIGHT = 53;
  const virtualized = files.length > VIRTUALIZE_THRESHOLD;
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: virtualized ? files.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 5
  });

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

  const renderRow = (file: FileRecord) => (
    <TableRow key={file.id} style={virtualized ? { height: ROW_HEIGHT } : undefined}>
      <TableCell className='font-medium'>{file.name}</TableCell>
      <TableCell>{formatSize(file.size)}</TableCell>
      <TableCell>{formatDate(file.created_at)}</TableCell>
      <TableCell className='text-right'>
        <div className='flex justify-end gap-2'>
          {isImage(file) && <PreviewButton file={file} />}
          <ShareFileDialog file={file} />
          <Button variant='outline' size='sm' onClick={() => downloadFile(file)}>
            <Icons.download className='mr-1.5 h-4 w-4' />
            Download
          </Button>
          <Button
            variant='destructive'
            size='sm'
            onClick={() =>
              remove.mutate(file.id, {
                onError: (err) => toast.error(err instanceof Error ? err.message : 'Delete failed')
              })
            }
            disabled={remove.isPending}
          >
            <Icons.trash className='mr-1.5 h-4 w-4' />
            Delete
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );

  if (virtualized) {
    const items = virtualizer.getVirtualItems();
    const padTop = items.length > 0 ? items[0].start : 0;
    const padBottom =
      items.length > 0 ? virtualizer.getTotalSize() - items[items.length - 1].end : 0;
    return (
      <div ref={scrollRef} className='max-h-[70vh] overflow-y-auto'>
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
            {padTop > 0 && (
              <TableRow aria-hidden='true'>
                <TableCell colSpan={4} style={{ height: padTop, padding: 0, border: 0 }} />
              </TableRow>
            )}
            {items.map((vi) => renderRow(files[vi.index]))}
            {padBottom > 0 && (
              <TableRow aria-hidden='true'>
                <TableCell colSpan={4} style={{ height: padBottom, padding: 0, border: 0 }} />
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
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
        {files.map(renderRow)}
      </TableBody>
    </Table>
  );
}
