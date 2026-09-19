'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { motion } from 'motion/react';
import { cn } from '@/lib/utils';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import { Icons } from '@/components/icons';
import { Message, ReactionSummary } from '../api/types';

const REACTION_EMOJIS = ['👍', '❤️', '😂', '🎉', '👀'];

interface MessageListProps {
  messages: Message[];
  currentUserId?: string;
  onReply?: (message: Message) => void;
  onToggleReaction?: (message: Message, emoji: string) => void;
  onOpenThread?: (message: Message) => void;
  onEdit?: (message: Message, content: string) => void;
  onDelete?: (message: Message) => void;
}

function authorLabel(message: Message): string {
  return message.author_name || message.author_id;
}

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function ReactionChips({
  reactions,
  currentUserId,
  onToggle
}: {
  reactions: ReactionSummary[];
  currentUserId?: string;
  onToggle?: (emoji: string) => void;
}) {
  if (reactions.length === 0) return null;
  return (
    <div className='mt-1.5 flex flex-wrap gap-1'>
      {reactions.map((r) => {
        const mine = !!currentUserId && r.user_ids.includes(currentUserId);
        return (
          <button
            key={r.emoji}
            type='button'
            onClick={() => onToggle?.(r.emoji)}
            aria-pressed={mine}
            aria-label={`${r.emoji} reaction, ${r.count} ${r.count === 1 ? 'person' : 'people'}`}
            className={cn(
              'flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors',
              mine
                ? 'border-primary/60 bg-primary/15 text-primary'
                : 'border-border/60 bg-background/70 text-foreground/80 hover:bg-muted'
            )}
          >
            <span aria-hidden='true'>{r.emoji}</span>
            <span className='tabular-nums'>{r.count}</span>
          </button>
        );
      })}
    </div>
  );
}

function EmojiPicker({ onPick }: { onPick: (emoji: string) => void }) {
  return (
    <div
      role='menu'
      aria-label='Add reaction'
      className='border-border/60 bg-background flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 shadow-sm'
    >
      {REACTION_EMOJIS.map((emoji) => (
        <button
          key={emoji}
          type='button'
          role='menuitem'
          onClick={() => onPick(emoji)}
          aria-label={`React with ${emoji}`}
          className='hover:bg-muted rounded-full p-1 text-sm transition-transform hover:scale-110'
        >
          <span aria-hidden='true'>{emoji}</span>
        </button>
      ))}
    </div>
  );
}

// Source: shadcn/ui Avatar/Button + Slack-style thread row pattern.
function MessageBubble({
  message,
  isMe,
  compact = false,
  currentUserId,
  onToggleReaction,
  onEdit,
  onDelete
}: {
  message: Message;
  isMe: boolean;
  compact?: boolean;
  currentUserId?: string;
  onToggleReaction?: (emoji: string) => void;
  onEdit?: (content: string) => void;
  onDelete?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState(message.content);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
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
        {editing ? (
          <form
            className='mt-1 flex flex-col gap-1.5'
            onSubmit={(e) => {
              e.preventDefault();
              const content = editDraft.trim();
              if (content && content !== message.content) onEdit?.(content);
              setEditing(false);
            }}
          >
            <textarea
              value={editDraft}
              onChange={(e) => setEditDraft(e.target.value)}
              aria-label='Edit message'
              rows={2}
              className='border-border/60 bg-background text-foreground w-full rounded-lg border px-2 py-1 text-sm'
            />
            <div className='flex gap-1.5'>
              <Button type='submit' size='sm' className='h-7 px-2 text-xs'>
                Save
              </Button>
              <Button
                type='button'
                variant='ghost'
                size='sm'
                className='h-7 px-2 text-xs'
                onClick={() => {
                  setEditing(false);
                  setEditDraft(message.content);
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <p
            className={cn(
              'mt-1 whitespace-pre-wrap',
              isMe ? 'text-primary-foreground/90' : 'text-foreground/90'
            )}
          >
            {message.content}
          </p>
        )}
        <span
          className={cn(
            'mt-1 block text-[0.65rem] sm:text-[0.7rem]',
            isMe ? 'text-primary-foreground/70' : 'text-muted-foreground'
          )}
        >
          {timeLabel(message.created_at)}
          {message.updated_at !== message.created_at && ' · edited'}
        </span>
        {isMe && !editing && (onEdit || onDelete) && (
          <span className='mt-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100'>
            {onEdit && (
              <button
                type='button'
                onClick={() => setEditing(true)}
                aria-label={`Edit message from ${authorLabel(message)}`}
                className={cn(
                  'text-[0.65rem] underline underline-offset-2',
                  isMe ? 'text-primary-foreground/80' : 'text-muted-foreground'
                )}
              >
                Edit
              </button>
            )}
            {onDelete && (
              <AlertDialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
                <AlertDialogTrigger
                  aria-label={`Delete message from ${authorLabel(message)}`}
                  className={cn(
                    'text-[0.65rem] underline underline-offset-2',
                    isMe ? 'text-primary-foreground/80' : 'text-destructive'
                  )}
                >
                  Delete
                </AlertDialogTrigger>
                <AlertDialogContent size='sm'>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete this message?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This is permanent — the message is removed for everyone in the channel and
                      cannot be restored.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      variant='destructive'
                      aria-label='Confirm delete message'
                      onClick={() => {
                        setConfirmingDelete(false);
                        onDelete();
                      }}
                    >
                      Delete
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </span>
        )}
        <ReactionChips
          reactions={message.reactions ?? []}
          currentUserId={currentUserId}
          onToggle={onToggleReaction}
        />
      </div>
    </div>
  );
}

export function MessageList({
  messages,
  currentUserId,
  onReply,
  onToggleReaction,
  onOpenThread,
  onEdit,
  onDelete
}: MessageListProps) {
  // Animations always run at full intensity; OS reduced-motion is ignored by design.
  const shouldReduceMotion = false;
  const scrollRef = useRef<HTMLDivElement>(null);

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

  // Windowing: above the threshold only the visible slice mounts (react-virtual
  // with dynamic row measurement). Below it the plain list renders so small
  // channels keep simple DOM and entry animations.
  const VIRTUALIZE_THRESHOLD = 50;
  const virtualized = roots.length > VIRTUALIZE_THRESHOLD;
  const virtualizer = useVirtualizer({
    count: virtualized ? roots.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 96,
    overscan: 8,
    getItemKey: (i) => roots[i]?.id ?? i
  });

  // New messages land at the bottom; keep the view pinned there on first
  // render and whenever the list grows while already near the bottom.
  const lastCountRef = useRef(roots.length);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !virtualized) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
    if (roots.length !== lastCountRef.current && nearBottom) {
      el.scrollTop = el.scrollHeight;
    }
    lastCountRef.current = roots.length;
  }, [roots.length, virtualized]);

  const renderMessage = (message: Message) => {
    const isMe = message.author_id === currentUserId;
    // Optimistic messages carry a `pending-` id that the server doesn't know
    // yet — acting on them (reply/edit/delete/react) would send a bogus id and
    // roll back. Hide the actions until the refetch swaps in the real id.
    const isPending = message.id.startsWith('pending-');
    const replies = repliesByParent.get(message.id) ?? [];
    const lastReply = replies[replies.length - 1];
    return (
      <div className='group flex flex-col gap-2'>
        <div className='flex items-center gap-2'>
          <div className='min-w-0 flex-1'>
            <MessageBubble
              message={message}
              isMe={isMe}
              currentUserId={currentUserId}
              onToggleReaction={
                onToggleReaction && !isPending
                  ? (emoji) => onToggleReaction(message, emoji)
                  : undefined
              }
              onEdit={onEdit && !isPending ? (content) => onEdit(message, content) : undefined}
              onDelete={onDelete && !isPending ? () => onDelete(message) : undefined}
            />
          </div>
          {onToggleReaction && !isPending && (
            <div className='opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100'>
              <EmojiPicker onPick={(emoji) => onToggleReaction(message, emoji)} />
            </div>
          )}
          {onReply && !isPending && (
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
              onClick={() => onOpenThread?.(message)}
            >
              {replies.length === 1 ? '1 reply' : `${replies.length} replies`}
              {lastReply && ` · last ${timeLabel(lastReply.created_at)}`} — open thread
            </Button>
          </div>
        )}
      </div>
    );
  };

  return (
    <div
      ref={scrollRef}
      className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-2 py-4 sm:px-4'
      aria-label='Messages'
      role='log'
    >
      {roots.length === 0 ? (
        <Empty className='flex-1'>
          <EmptyHeader>
            <EmptyMedia variant='icon' className='size-12 rounded-full'>
              <Icons.chat className='size-6' />
            </EmptyMedia>
            <EmptyTitle>No messages yet</EmptyTitle>
            <EmptyDescription>Start the conversation below.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : virtualized ? (
        <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualizer.getVirtualItems().map((vi) => (
            <div
              key={vi.key}
              data-index={vi.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${vi.start}px)`
              }}
              className='pb-4'
            >
              {renderMessage(roots[vi.index])}
            </div>
          ))}
        </div>
      ) : (
        roots.map((message) => (
          <motion.div
            key={message.id}
            initial={shouldReduceMotion ? false : { opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.28, ease: 'easeOut' }}
          >
            {renderMessage(message)}
          </motion.div>
        ))
      )}
    </div>
  );
}
