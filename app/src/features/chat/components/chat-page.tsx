'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import type { Channel, DMChannel, Message } from '../api/types';
import { CreateChannelPayload } from '../api/types';
import {
  getChannels,
  getDMs,
  getMessages,
  sendMessage,
  createChannel,
  createDM,
  toggleReaction
} from '../api/service';
import { NewDMDialog } from './new-dm-dialog';
import { channelKeys } from '../api/queries';
import { useChannelWebSocket } from '../utils/use-channel-websocket';
import { ChannelList } from './channel-list';
import { MessageList } from './message-list';
import { MessageInput } from './message-input';
import { CreateChannelDialog } from './create-channel-dialog';

function buildOptimisticMessage(
  content: string,
  channelId: string,
  parentId: string | null = null,
  authorId: string = 'you'
): Message {
  return {
    id: `pending-${Date.now()}`,
    channel_id: channelId,
    author_id: authorId,
    content,
    parent_id: parentId,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    reactions: []
  };
}

export default function ChatPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [replyingTo, setReplyingTo] = useState<Message | null>(null);

  const meQuery = useQuery<{ id: string } | null>({
    queryKey: ['auth', 'me'],
    queryFn: async () => {
      const res = await fetch('/api/auth/me', { credentials: 'include' });
      if (!res.ok) return null;
      const data = (await res.json().catch(() => ({}))) as { user?: { id: string } | null };
      return data.user ?? null;
    },
    staleTime: 5 * 60 * 1000
  });
  const currentUserId = meQuery.data?.id;

  const channelsQuery = useQuery<Channel[]>({
    queryKey: channelKeys.list(),
    queryFn: async () => getChannels()
  });

  const dmsQuery = useQuery<DMChannel[]>({
    queryKey: channelKeys.dms(),
    queryFn: getDMs
  });

  const allChannels = useMemo(
    () => [...(channelsQuery.data ?? []), ...(dmsQuery.data ?? [])],
    [channelsQuery.data, dmsQuery.data]
  );

  const selectedChannel = useMemo(
    () => allChannels.find((c) => c.id === selectedId) ?? allChannels[0] ?? null,
    [allChannels, selectedId]
  );

  const selectedDM = useMemo(
    () => dmsQuery.data?.find((d) => d.id === selectedChannel?.id) ?? null,
    [dmsQuery.data, selectedChannel]
  );

  const createDMMutation = useMutation({
    mutationFn: createDM,
    onSuccess: (dm) => {
      void queryClient.invalidateQueries({ queryKey: channelKeys.dms() });
      setSelectedId(dm.id);
      toast.success(`Chat with ${dm.peer_name ?? 'member'} ready`);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to open DM');
    }
  });

  const messagesQuery = useQuery<Message[]>({
    queryKey: channelKeys.messages(selectedChannel?.id ?? null),
    queryFn: async () => {
      if (!selectedChannel) return [];
      return getMessages(selectedChannel.id);
    },
    enabled: !!selectedChannel
  });

  const createChannelMutation = useMutation({
    mutationFn: createChannel,
    onSuccess: (channel) => {
      void queryClient.invalidateQueries({ queryKey: channelKeys.all });
      setSelectedId(channel.id);
      toast.success('Channel created');
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to create channel');
    }
  });

  const handleCreateChannel = async (payload: CreateChannelPayload) => {
    await createChannelMutation.mutateAsync(payload);
  };

  const sendMessageMutation = useMutation({
    mutationFn: async (content: string) => {
      if (!selectedChannel) throw new Error('No channel selected');
      return sendMessage(selectedChannel.id, {
        content,
        parent_id: replyingTo?.id ?? null
      });
    },
    onMutate: async (content) => {
      if (!selectedChannel) return;
      const key = channelKeys.messages(selectedChannel.id);
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<Message[]>(key);
      const optimistic = buildOptimisticMessage(
        content,
        selectedChannel.id,
        replyingTo?.id ?? null,
        currentUserId ?? 'you'
      );
      queryClient.setQueryData<Message[]>(key, (old) => [...(old ?? []), optimistic]);
      return { previous, key };
    },
    onError: (err, _content, context) => {
      if (context?.key) {
        queryClient.setQueryData<Message[]>(context.key, context.previous ?? []);
      }
      toast.error(err instanceof Error ? err.message : 'Failed to send message');
    },
    onSettled: (_data, _error, _content, context) => {
      if (context?.key) {
        void queryClient.invalidateQueries({ queryKey: context.key });
      }
      setDraft('');
      setReplyingTo(null);
    }
  });

  const handleSend = (content: string) => {
    sendMessageMutation.mutate(content);
  };

  const reactionMutation = useMutation({
    mutationFn: async ({ messageId, emoji }: { messageId: string; emoji: string }) =>
      toggleReaction(messageId, emoji),
    onSuccess: (reactions, { messageId }) => {
      if (!selectedChannel) return;
      const key = channelKeys.messages(selectedChannel.id);
      queryClient.setQueryData<Message[]>(key, (old) =>
        (old ?? []).map((m) => (m.id === messageId ? { ...m, reactions } : m))
      );
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to react');
    }
  });

  const handleToggleReaction = (message: Message, emoji: string) => {
    if (message.id.startsWith('pending-')) return;
    reactionMutation.mutate({ messageId: message.id, emoji });
  };

  // Realtime WebSocket: append incoming messages for the selected channel.
  useChannelWebSocket({
    channelId: selectedChannel?.id ?? undefined,
    onMessage: (data: unknown) => {
      if (!data || typeof data !== 'object') return;
      const payload = data as {
        type?: string;
        message?: Message;
        message_id?: string;
        reactions?: Message['reactions'];
      };
      if (payload.type === 'new_message' && payload.message) {
        const msg = payload.message;
        if (msg.channel_id !== selectedChannel?.id) return;
        void queryClient.setQueryData<Message[]>(channelKeys.messages(msg.channel_id), (old) =>
          old ? [...old, msg] : [msg]
        );
      } else if (payload.type === 'reaction_update' && payload.message_id) {
        if (!selectedChannel) return;
        const { message_id, reactions } = payload;
        void queryClient.setQueryData<Message[]>(
          channelKeys.messages(selectedChannel.id),
          (old) =>
            (old ?? []).map((m) => (m.id === message_id ? { ...m, reactions } : m))
        );
      }
    }
  });

  return (
    <PageContainer pageTitle='Chat' pageDescription='Workspace channels and messages.'>
      <div
        className={cn(
          'border-border/50 bg-background/70 relative grid h-[calc(100dvh-10rem)] w-full gap-3 overflow-hidden rounded-2xl border p-3 backdrop-blur-xl sm:p-4 lg:grid-cols-[320px_1fr] lg:rounded-3xl'
        )}
      >
        <ChannelList
          channels={channelsQuery.data ?? []}
          dms={dmsQuery.data ?? []}
          selectedId={selectedChannel?.id ?? null}
          onSelect={setSelectedId}
          action={
            <CreateChannelDialog
              onSubmit={handleCreateChannel}
              isSubmitting={createChannelMutation.isPending}
            />
          }
          dmAction={
            <NewDMDialog
              currentUserId={currentUserId}
              onSubmit={async (userId) => {
                await createDMMutation.mutateAsync(userId);
              }}
              isSubmitting={createDMMutation.isPending}
            />
          }
        />

        <div className='flex min-h-0 flex-col gap-3 overflow-hidden rounded-2xl border border-transparent bg-transparent sm:gap-4'>
          {selectedChannel ? (
            <>
              <header className='border-border/40 bg-background/80 flex items-center justify-between rounded-2xl border px-4 py-3 backdrop-blur sm:px-6'>
                <div>
                  <h2 className='text-foreground text-base font-semibold sm:text-lg'>
                    {selectedDM ? (selectedDM.peer_name ?? 'Direct message') : `#${selectedChannel.name}`}
                  </h2>
                  <p className='text-muted-foreground text-xs capitalize'>
                    {selectedDM ? 'Direct message' : `${selectedChannel.type} channel`}
                  </p>
                </div>
              </header>

              {messagesQuery.isLoading ? (
                <div className='flex flex-1 flex-col gap-4 px-4 py-6'>
                  <Skeleton className='h-16 w-3/4' />
                  <Skeleton className='h-16 w-1/2 self-end' />
                  <Skeleton className='h-16 w-2/3' />
                </div>
              ) : (
                <MessageList
                  messages={messagesQuery.data ?? []}
                  currentUserId={currentUserId}
                  onReply={setReplyingTo}
                  onToggleReaction={handleToggleReaction}
                />
              )}

              <MessageInput
                value={draft}
                onChange={setDraft}
                onSubmit={handleSend}
                placeholder={
                  replyingTo
                    ? `Reply to ${replyingTo.author_name || replyingTo.author_id}...`
                    : selectedDM
                      ? `Message ${selectedDM.peer_name ?? 'direct message'}`
                      : `Message #${selectedChannel.name}`
                }
                disabled={sendMessageMutation.isPending}
                replyingTo={
                  replyingTo ? replyingTo.author_name || replyingTo.author_id : null
                }
                onCancelReply={() => setReplyingTo(null)}
              />
            </>
          ) : (
            <div className='flex flex-1 items-center justify-center'>
              <p className='text-muted-foreground text-sm'>Select a channel to start chatting.</p>
            </div>
          )}
        </div>
      </div>
    </PageContainer>
  );
}
