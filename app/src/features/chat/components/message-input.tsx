'use client';

import { FormEvent } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

interface MessageInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  replyingTo?: string | null;
  onCancelReply?: () => void;
}

export function MessageInput({
  value,
  onChange,
  onSubmit,
  placeholder = 'Write a message...',
  disabled = false,
  replyingTo,
  onCancelReply
}: MessageInputProps) {
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!value.trim() || disabled) return;
    onSubmit(value.trim());
  };

  return (
    <form onSubmit={handleSubmit} className='shrink-0' aria-label='Message composer'>
      {replyingTo && (
        <div className='mb-2 flex items-center justify-between rounded-lg border border-border/40 bg-muted/60 px-3 py-1.5 text-xs text-muted-foreground'>
          <span>
            Replying to <span className='font-medium text-foreground'>{replyingTo}</span>
          </span>
          <button
            type='button'
            onClick={onCancelReply}
            className='text-muted-foreground hover:text-foreground'
            aria-label='Cancel reply'
          >
            ✕
          </button>
        </div>
      )}
      <div className='border-border/40 bg-background/80 flex items-end gap-2 rounded-2xl border p-3 backdrop-blur sm:gap-3 sm:rounded-3xl sm:p-4'>
        <Textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (value.trim() && !disabled) {
                const form = e.currentTarget.closest('form');
                form?.requestSubmit();
              }
            }
          }}
          placeholder={placeholder}
          rows={2}
          disabled={disabled}
          className='text-foreground placeholder:text-muted-foreground/70 min-h-[3rem] w-full resize-none border-none bg-transparent text-sm focus-visible:ring-0 focus-visible:outline-none sm:min-h-[4rem]'
          aria-label='Write a message'
        />
        <div className='flex shrink-0 flex-col items-end gap-1.5 sm:gap-2'>
          <Button
            type='submit'
            size='icon'
            disabled={!value.trim() || disabled}
            className='bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-primary/40 focus-visible:ring-offset-background size-8 rounded-full shadow-sm transition focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 sm:size-10'
            aria-label='Send message'
          >
            <Icons.send className='h-3.5 w-3.5 sm:h-4 sm:w-4' aria-hidden='true' />
          </Button>
        </div>
      </div>
    </form>
  );
}
