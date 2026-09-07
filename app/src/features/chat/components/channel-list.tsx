'use client';

import { useMemo, useState } from 'react';
import { motion } from 'motion/react';
import { Icons } from '@/components/icons';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { Channel } from '../api/types';

interface ChannelListProps {
  channels: Channel[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  action?: React.ReactNode;
}

export function ChannelList({ channels, selectedId, onSelect, action }: ChannelListProps) {
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search.trim()) return channels;
    const q = search.toLowerCase();
    return channels.filter((c) => c.name.toLowerCase().includes(q));
  }, [channels, search]);

  return (
    <div className='border-border/40 bg-background/75 flex h-full min-w-0 flex-col gap-4 overflow-hidden rounded-2xl border p-3 backdrop-blur lg:rounded-3xl lg:p-4'>
      <div className='flex items-center justify-between gap-3'>
        <div>
          <p className='text-foreground text-sm font-semibold'>Channels</p>
          <p className='text-muted-foreground text-xs'>
            {channels.length} channel{channels.length === 1 ? '' : 's'}
          </p>
        </div>
        <div className='flex items-center gap-2'>
          <Badge
            variant='outline'
            className='bg-primary/15 text-primary hover:bg-primary/15 hover:text-primary border-border/50 rounded-full border px-3 py-1 text-[0.7rem] tracking-[0.24em] uppercase'
          >
            Live
          </Badge>
          {action}
        </div>
      </div>

      <label htmlFor='channel-search' className='sr-only'>
        Search channels
      </label>
      <div className='relative'>
        <Icons.search
          className='text-muted-foreground/70 pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2'
          aria-hidden='true'
        />
        <Input
          id='channel-search'
          type='search'
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder='Search channels'
          className='border-border/40 bg-background/60 text-foreground placeholder:text-muted-foreground/70 focus-visible:ring-primary/40 w-full rounded-2xl pl-10 text-sm focus-visible:ring-2'
        />
      </div>

      <div className='flex-1 space-y-2 overflow-y-auto pr-1' aria-label='Channel list' role='list'>
        {filtered.length === 0 ? (
          <p className='text-muted-foreground py-8 text-center text-xs'>No channels found</p>
        ) : null}
        {filtered.map((channel) => {
          const isActive = channel.id === selectedId;
          return (
            <motion.button
              key={channel.id}
              type='button'
              onClick={() => onSelect(channel.id)}
              aria-current={isActive ? 'true' : undefined}
              className={cn(
                'focus-visible:ring-primary/50 focus-visible:ring-offset-background group relative flex w-full items-center gap-3 rounded-2xl border border-transparent p-3 text-left transition-all focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none',
                isActive
                  ? 'border-primary/40 bg-primary/10'
                  : 'bg-background/70 hover:border-border/40 hover:bg-muted/40'
              )}
              role='listitem'
              whileTap={{ scale: 0.98 }}
            >
              <Avatar className='border-border/40 bg-background/80 text-foreground h-10 w-10 rounded-2xl border shrink-0'>
                <AvatarFallback className='bg-primary/15 text-primary rounded-2xl text-sm font-medium'>
                  {channel.name.slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className='min-w-0 flex-1 space-y-0.5 text-left'>
                <p className='text-foreground truncate text-sm font-semibold'>{channel.name}</p>
                <p className='text-muted-foreground text-xs capitalize'>
                  {channel.type}
                  {channel.is_private && ' · private'}
                </p>
              </div>
              <Icons.chevronRight
                className={cn(
                  'h-4 w-4 shrink-0 transition-opacity',
                  isActive
                    ? 'text-primary opacity-100'
                    : 'text-muted-foreground/50 opacity-0 group-hover:opacity-100'
                )}
                aria-hidden='true'
              />
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}
