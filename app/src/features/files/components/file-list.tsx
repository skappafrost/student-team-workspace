'use client';

import { useSuspenseQuery } from '@tanstack/react-query';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { FileRecord } from '../api/types';
import { formatSize, downloadFile } from '../api/service';
import { filesQueryOptions, useDeleteFile } from '../api/queries';

function formatDate(iso: string) {
  return new Date(iso).toLocaleString();
}

export function FileList() {
  const { data: files } = useSuspenseQuery(filesQueryOptions());
  const remove = useDeleteFile();

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
            <TableCell colSpan={4} className='h-24 text-center text-muted-foreground'>
              No files uploaded yet.
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
                <Button variant='outline' size='sm' onClick={() => downloadFile(file)}>
                  <Icons.download className='mr-1.5 h-4 w-4' />
                  Download
                </Button>
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
