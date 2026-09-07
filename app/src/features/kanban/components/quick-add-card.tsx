'use client';

// Quick-add card, column-bottom affordance per D7 references:
// kanban-workspace__shadcn-kanban-board ("+ New card" inline textarea form)
// and focalboard. Creates with title only; full dialog stays in page header.

import { useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';

interface QuickAddCardProps {
  onAdd: (title: string) => void;
}

export function QuickAddCard({ onAdd }: QuickAddCardProps) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState('');
  const buttonRef = useRef<HTMLButtonElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const startEditing = () => {
    flushSync(() => setEditing(true));
    textareaRef.current?.focus();
  };

  const cancel = () => {
    flushSync(() => {
      setEditing(false);
      setTitle('');
    });
    buttonRef.current?.focus();
  };

  const submit = () => {
    const trimmed = title.trim();
    if (!trimmed) {
      cancel();
      return;
    }
    onAdd(trimmed);
    setTitle('');
    textareaRef.current?.focus();
  };

  if (!editing) {
    return (
      <Button
        ref={buttonRef}
        variant='ghost'
        size='sm'
        className='text-muted-foreground hover:text-foreground w-full justify-start'
        onClick={startEditing}
      >
        <Icons.add />
        Add card
      </Button>
    );
  }

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- wrapper handles Escape/blur; interactive children carry their own handlers
    <form
      className='flex flex-col gap-2'
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') cancel();
      }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) cancel();
      }}
    >
      <textarea
        ref={textareaRef}
        name='cardContent'
        rows={2}
        aria-label='New card'
        placeholder='Enter a title...'
        required
        value={title}
        onChange={(e) => setTitle(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            e.currentTarget.form?.requestSubmit();
          }
        }}
        className={cn(
          'border-input bg-background focus-visible:border-ring focus-visible:ring-ring/50',
          'placeholder:text-muted-foreground text-sm shadow-xs transition-colors',
          'focus-visible:ring-3 rounded-lg border px-2.5 py-2 outline-none resize-none'
        )}
      />
      <div className='flex gap-1.5'>
        <Button type='submit' size='sm'>
          Add
        </Button>
        <Button type='button' variant='outline' size='sm' onClick={cancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
