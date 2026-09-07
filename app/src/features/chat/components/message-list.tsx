'use client';

import { useMemo } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { cn } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Message } from '../api/types';

interface MessageListProps {
  messages: Message[];
  currentUserId?: string;
}

export function MessageList({ messages, currentUserId }: MessageListProps) {
  const shouldReduceMotion = useReducedMotion();

  const grouped = useMemo(() => {
    return messages.map((message) => ({
      ...message,
      isMe: message.author_id === currentUserId
    }));
  }, [messages, currentUserId]);

  return (
    <div
      className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-2 py-4 sm:px-4'
      aria-label='Messages'
      role='log'
    >
      {grouped.length === 0 ? (
        <div className='flex flex-1 items-center justify-center'>
          <p className='text-muted-foreground text-sm'>No messages yet. Start the conversation!</p>
        </div>
      ) : (
        grouped.map((message) => (
          <motion.div
            key={message.id}
            initial={shouldReduceMotion ? false : { opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.28, ease: 'easeOut' }}
            className={cn(
              'flex w-full items-end gap-3',
              message.isMe ? 'flex-row-reverse' : 'flex-row'
            )}
            role='group'
            aria-label={`Message from ${message.author_name || message.author_id}`}
          >
            <Avatar className='border-border/40 bg-background/80 text-foreground h-8 w-8 rounded-xl border shrink-0 sm:h-9 sm:w-9'>
              <AvatarFallback className='bg-primary/15 text-primary rounded-xl text-xs font-medium'>
                {message.author_id.slice(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div
              className={cn(
                'relative max-w-[80%] rounded-2xl border px-4 py-2.5 text-sm leading-relaxed sm:max-w-[70%]',
                message.isMe
                  ? 'border-primary/40 bg-primary text-primary-foreground rounded-br-sm'
                  : 'bg-muted border-transparent rounded-bl-sm'
              )}
            >
              <p
                className={cn(
                  'text-xs font-medium',
                  message.isMe ? 'text-primary-foreground/80' : 'text-foreground/80'
                )}
              >
                {message.author_name || message.author_id}
              </p>
              <p
                className={cn(
                  'mt-1 whitespace-pre-wrap',
                  message.isMe ? 'text-primary-foreground/90' : 'text-foreground/90'
                )}
              >
                {message.content}
              </p>
              <span
                className={cn(
                  'mt-1 block text-[0.65rem] sm:text-[0.7rem]',
                  message.isMe ? 'text-primary-foreground/70' : 'text-muted-foreground'
                )}
              >
                {new Date(message.created_at).toLocaleTimeString('en-US', {
                  hour: '2-digit',
                  minute: '2-digit'
                })}
              </span>
            </div>
          </motion.div>
        ))
      )}
    </div>
  );
}
