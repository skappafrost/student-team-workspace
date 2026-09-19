'use client';

import { useState } from 'react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { Message } from '../api/types';
import { MessageInput } from './message-input';

// Source: Slack/Linear thread sidebar idiom — parent message pinned at top,
// replies listed below, dedicated composer at the bottom of the panel.

function authorLabel(message: Message): string {
  return message.author_name || message.author_id;
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

interface ThreadPanelProps {
  parent: Message;
  replies: Message[];
  currentUserId?: string;
  onClose: () => void;
  onSendReply: (content: string) => void;
  sending?: boolean;
}

/**
 * Thread side panel: parent message, reply list, dedicated reply composer.
 * Rendered beside the message list; closing returns focus to the main flow.
 */
export function ThreadPanel({
  parent,
  replies,
  currentUserId,
  onClose,
  onSendReply,
  sending = false
}: ThreadPanelProps) {
  const [draft, setDraft] = useState('');

  return (
    <aside
      aria-label={`Thread started by ${authorLabel(parent)}`}
      className='border-border/40 bg-background/80 flex h-full min-h-0 w-full flex-col rounded-2xl border backdrop-blur lg:w-80 xl:w-96'
    >
      <header className='border-border/40 flex items-center justify-between border-b px-4 py-3'>
        <div>
          <h3 className='text-foreground text-sm font-semibold'>Thread</h3>
          <p className='text-muted-foreground text-xs'>
            {replies.length === 0
              ? 'No replies yet'
              : `${replies.length} ${replies.length === 1 ? 'reply' : 'replies'}`}
          </p>
        </div>
        <Button
          type='button'
          variant='ghost'
          size='icon'
          onClick={onClose}
          aria-label='Close thread'
          className='size-8'
        >
          <Icons.close className='h-4 w-4' aria-hidden='true' />
        </Button>
      </header>

      <div className='min-h-0 flex-1 overflow-y-auto px-4 py-3'>
        {/* Parent message, pinned at the top of the thread */}
        <div className='border-border/40 bg-muted/40 rounded-xl border p-3'>
          <div className='flex items-center gap-2'>
            <Avatar className='border-border/40 h-6 w-6 rounded-lg border'>
              <AvatarFallback className='bg-primary/15 text-primary rounded-lg text-[0.6rem] font-medium'>
                {authorLabel(parent).slice(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <span className='text-foreground text-xs font-medium'>{authorLabel(parent)}</span>
            <span className='text-muted-foreground text-[0.65rem]'>
              {timeLabel(parent.created_at)}
            </span>
          </div>
          <p className='text-foreground/90 mt-1.5 text-sm whitespace-pre-wrap'>{parent.content}</p>
        </div>

        <div className='mt-3 flex flex-col gap-3'>
          {replies.map((reply) => (
            <div
              key={reply.id}
              className={cn('flex gap-2', reply.author_id === currentUserId && 'flex-row-reverse')}
            >
              <Avatar className='border-border/40 h-6 w-6 shrink-0 rounded-lg border'>
                <AvatarFallback className='bg-primary/15 text-primary rounded-lg text-[0.6rem] font-medium'>
                  {authorLabel(reply).slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div
                className={cn(
                  'max-w-[85%] rounded-xl border px-3 py-2 text-sm',
                  reply.author_id === currentUserId
                    ? 'border-primary/40 bg-primary text-primary-foreground'
                    : 'bg-muted border-transparent'
                )}
              >
                <p
                  className={cn(
                    'text-xs font-medium',
                    reply.author_id === currentUserId
                      ? 'text-primary-foreground/80'
                      : 'text-foreground/80'
                  )}
                >
                  {authorLabel(reply)}
                </p>
                <p className='mt-0.5 whitespace-pre-wrap'>{reply.content}</p>
                <span
                  className={cn(
                    'mt-0.5 block text-[0.6rem]',
                    reply.author_id === currentUserId
                      ? 'text-primary-foreground/70'
                      : 'text-muted-foreground'
                  )}
                >
                  {timeLabel(reply.created_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className='border-border/40 border-t p-3'>
        <MessageInput
          value={draft}
          onChange={setDraft}
          onSubmit={(content) => {
            onSendReply(content);
            setDraft('');
          }}
          placeholder={`Reply to ${authorLabel(parent)}…`}
          disabled={sending}
        />
      </div>
    </aside>
  );
}
