'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { LoadingButton } from '@/components/ui/loading-button';
import { Icons } from '@/components/icons';
import { channelsQueryOptions, channelKeys } from '@/features/chat/api/queries';
import { sendMessage } from '@/features/chat/api/service';
import { useUpdateFile } from '../api/queries';
import { FileRecord } from '../api/types';

// Source: shadcn/ui Dialog + Select; chat feature's channel query.
export function ShareFileDialog({ file }: { file: FileRecord }) {
  const [open, setOpen] = useState(false);
  const [channelId, setChannelId] = useState<string>('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: channels } = useQuery(channelsQueryOptions());
  const updateFile = useUpdateFile();
  const queryClient = useQueryClient();

  const onShare = async () => {
    if (!channelId) return;
    setPending(true);
    setError(null);
    try {
      const message = await sendMessage(channelId, {
        content: `Shared a file: [${file.name}](${file.url}) (${formatBytes(file.size)})`
      });
      await updateFile.mutateAsync({ id: file.id, payload: { message_id: message.id } });
      void queryClient.invalidateQueries({ queryKey: channelKeys.messages(channelId) });
      setOpen(false);
      setChannelId('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to share file');
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant='outline' size='sm'>
            <Icons.share className='mr-1.5 h-4 w-4' />
            Share
          </Button>
        }
      />
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Share to chat</DialogTitle>
          <DialogDescription>
            Post a link to &quot;{file.name}&quot; in a channel.
          </DialogDescription>
        </DialogHeader>
        <Select value={channelId} onValueChange={(value) => setChannelId(value ?? '')}>
          <SelectTrigger aria-label='Channel'>
            <SelectValue placeholder='Select a channel' />
          </SelectTrigger>
          <SelectContent>
            {(channels ?? []).map((c) => (
              <SelectItem key={c.id} value={c.id}>
                # {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {error && <p className='text-sm text-destructive'>{error}</p>}
        <DialogFooter showCloseButton>
          <LoadingButton onClick={onShare} disabled={!channelId} loading={pending}>
            Share
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}
