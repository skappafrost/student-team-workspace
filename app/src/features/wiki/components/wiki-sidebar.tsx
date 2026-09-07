'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { Icons } from '@/components/icons';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { WikiPageSummary } from '../api/types';

interface WikiSidebarProps {
  pages: WikiPageSummary[];
  recentPages: WikiPageSummary[];
  selectedId: string | null;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  onSelect: (id: string) => void;
}

export function WikiSidebar({
  pages,
  recentPages,
  selectedId,
  searchQuery,
  onSearchChange,
  onSelect
}: WikiSidebarProps) {
  return (
    <div
      className={cn(
        'border-border/50 bg-background/70 flex h-full flex-col overflow-hidden rounded-2xl border backdrop-blur-xl'
      )}
    >
      <div className='border-b px-3 py-2.5 font-medium text-sm'>Pages</div>

      <div className='space-y-2 px-3 py-2'>
        <div className='relative'>
          <Icons.search className='text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2' />
          <Input
            type='text'
            placeholder='Search pages...'
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className='bg-background/50 pl-9 text-sm'
          />
        </div>

        {searchQuery.trim() === '' && recentPages.length > 0 && (
          <div className='space-y-1.5'>
            <h4 className='text-muted-foreground text-xs font-medium uppercase tracking-wide'>
              Recent
            </h4>
            <ScrollArea className='h-auto max-h-[160px]'>
              <div className='flex flex-col gap-0.5'>
                {recentPages.map((page) => (
                  <button
                    key={page.id}
                    type='button'
                    onClick={() => onSelect(page.id)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                      selectedId === page.id ? 'bg-accent text-accent-foreground' : 'hover:bg-muted'
                    )}
                  >
                    <Icons.clock className='text-muted-foreground size-4 shrink-0' />
                    <span className='truncate'>{page.title}</span>
                  </button>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}
      </div>

      <ScrollArea className='flex-1 px-2 pb-2'>
        {pages.length === 0 ? (
          <div className='text-muted-foreground px-2 py-4 text-center text-sm'>No pages found.</div>
        ) : (
          <div className='flex flex-col gap-0.5'>
            {pages.map((page) => (
              <button
                key={page.id}
                type='button'
                onClick={() => onSelect(page.id)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                  selectedId === page.id ? 'bg-accent text-accent-foreground' : 'hover:bg-muted'
                )}
              >
                <Icons.page className='text-muted-foreground size-4 shrink-0' />
                <span className='truncate'>{page.title}</span>
              </button>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
