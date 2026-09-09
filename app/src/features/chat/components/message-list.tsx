'use client';

import { useMemo, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { cn } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Message } from '../api/types';

interface MessageListProps {
  messages: Message[];
  currentUserId?: string;
  onReply?: (message: Message) => void;
}

function authorLabel(message: Message): string {
  return message.author_name || message.author_id;
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

// Source: shadcn/ui Avatar/Button + Slack-style thread row pattern.
function MessageBubble({
  message,
  isMe,
  compact = false
}: {
  message: Message;
  isMe: boolean;
  compact?: boolean;
}) {
  return (
    <div
      className={cn('flex w-full items-end gap-3', isMe ? 'flex-row-reverse' : 'flex-row')}
      role='group'
      aria-label={`Message from ${authorLabel(message)}`}
    >
      <Avatar
        className={cn(
          'border-border/40 bg-background/80 text-foreground rounded-xl border shrink-0',
          compact ? 'h-6 w-6' : 'h-8 w-8 sm:h-9 sm:w-9'
        )}
      >
        <AvatarFallback className='bg-primary/15 text-primary rounded-xl text-xs font-medium'>
          {authorLabel(message).slice(0, 2).toUpperCase()}
        </AvatarFallback>
      </Avatar>
      <div
        className={cn(
          'relative max-w-[80%] rounded-2xl border px-4 py-2.5 text-sm leading-relaxed sm:max-w-[70%]',
          isMe
            ? 'border-primary/40 bg-primary text-primary-foreground rounded-br-sm'
            : 'bg-muted border-transparent rounded-bl-sm'
        )}
      >
        <p
          className={cn(
            'text-xs font-medium',
            isMe ? 'text-primary-foreground/80' : 'text-foreground/80'
          )}
        >
          {authorLabel(message)}
        </p>
        <p
          className={cn(
            'mt-1 whitespace-pre-wrap',
            isMe ? 'text-primary-foreground/90' : 'text-foreground/90'
          )}
        >
          {message.content}
        </p>
        <span
          className={cn(
            'mt-1 block text-[0.65rem] sm:text-[0.7rem]',
            isMe ? 'text-primary-foreground/70' : 'text-muted-foreground'
          )}
        >
          {timeLabel(message.created_at)}
        </span>
      </div>
    </div>
  );
}

export function MessageList({ messages, currentUserId, onReply }: MessageListProps) {
  const shouldReduceMotion = useReducedMotion();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const { roots, repliesByParent } = useMemo(() => {
    const roots: Message[] = [];
    const repliesByParent = new Map<string, Message[]>();
    for (const m of messages) {
      if (m.parent_id) {
        const list = repliesByParent.get(m.parent_id) ?? [];
        list.push(m);
        repliesByParent.set(m.parent_id, list);
      } else {
        roots.push(m);
      }
    }
    return { roots, repliesByParent };
  }, [messages]);

  return (
    <div
      className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-2 py-4 sm:px-4'
      aria-label='Messages'
      role='log'
    >
      {roots.length === 0 ? (
        <div className='flex flex-1 items-center justify-center'>
          <p className='text-muted-foreground text-sm'>No messages yet. Start the conversation!</p>
        </div>
      ) : (
        roots.map((message) => {
          const isMe = message.author_id === currentUserId;
          const replies = repliesByParent.get(message.id) ?? [];
          const isOpen = expanded[message.id] ?? false;
          return (
            <motion.div
              key={message.id}
              initial={shouldReduceMotion ? false : { opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.28, ease: 'easeOut' }}
              className='group flex flex-col gap-2'
            >
              <div className='flex items-center gap-2'>
                <div className='min-w-0 flex-1'>
                  <MessageBubble message={message} isMe={isMe} />
                </div>
                {onReply && (
                  <Button
                    type='button'
                    variant='ghost'
                    size='sm'
                    className='opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100'
                    onClick={() => onReply(message)}
                    aria-label={`Reply to ${authorLabel(message)}`}
                  >
                    Reply
                  </Button>
                )}
              </div>
              {replies.length > 0 && (
                <div className={cn('ps-10 sm:ps-12', isMe && 'text-right')}>
                  <Button
                    type='button'
                    variant='link'
                    size='sm'
                    className='h-auto px-0 text-xs'
                    onClick={() =>
                      setExpanded((prev) => ({ ...prev, [message.id]: !isOpen }))
                    }
                    aria-expanded={isOpen}
                  >
                    {isOpen
                      ? `Hide ${replies.length === 1 ? 'reply' : `${replies.length} replies`}`
                      : `Show ${replies.length === 1 ? '1 reply' : `${replies.length} replies`}`}
                  </Button>
                  {isOpen && (
                    <div className='mt-2 flex flex-col gap-2'>
                      {replies.map((reply) => (
                        <MessageBubble
                          key={reply.id}
                          message={reply}
                          isMe={reply.author_id === currentUserId}
                          compact
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          );
        })
      )}
    </div>
  );
}
