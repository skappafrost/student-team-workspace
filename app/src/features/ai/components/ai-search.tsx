'use client';

/**
 * AI Search
 *
 * Sources (zero-native-design rule):
 * - Command palette shell: shadcn/ui Command + Dialog
 *   (https://ui.shadcn.com/docs/components/command)
 * - Search input: shadcn/ui CommandInput (cmdk primitive)
 * - Ranked result list: shadcn/ui CommandList + CommandGroup + CommandItem
 * - Loading state: shadcn/ui Skeleton
 * - Icons: project icon registry (@/components/icons)
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from '@/components/ui/command';
import { Skeleton } from '@/components/ui/skeleton';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/use-debounce';
import { aiSearchQueryOptions } from '../api/queries';

interface AISearchProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const KIND_ICONS: Record<string, typeof Icons.search> = {
  task: Icons.kanban,
  page: Icons.wiki,
  message: Icons.chat
};

const KIND_LABEL: Record<string, string> = {
  task: 'Task',
  page: 'Page',
  message: 'Message'
};

export function AISearch({ open, onOpenChange }: AISearchProps) {
  const [query, setQuery] = useState('');
  const debouncedQuery = useDebounce(query, 250);

  const searchQuery = useQuery({
    ...aiSearchQueryOptions(debouncedQuery),
    enabled: open && debouncedQuery.trim().length > 0
  });

  const results = searchQuery.data ?? [];

  const grouped: Record<string, typeof results> = {};
  for (const result of results) {
    if (!grouped[result.kind]) grouped[result.kind] = [];
    grouped[result.kind].push(result);
  }

  const isLoading = open && debouncedQuery.trim().length > 0 && searchQuery.isLoading;

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title='AI Search'
      description='Search across tasks, pages, and messages.'
    >
      <Command className='bg-transparent' shouldFilter={false}>
        <CommandInput
          placeholder='Search tasks, pages, messages...'
          value={query}
          onValueChange={setQuery}
        />
        <CommandList>
          {isLoading ? (
            <div className='space-y-2 p-2'>
              <Skeleton className='h-8 w-full' />
              <Skeleton className='h-8 w-full' />
              <Skeleton className='h-8 w-full' />
            </div>
          ) : query.trim().length === 0 ? (
            <CommandEmpty className='py-8 text-center text-sm text-muted-foreground'>
              <div className='flex flex-col items-center gap-2'>
                <Icons.search className='h-6 w-6 opacity-40' />
                <p>Type a keyword to search across your workspace.</p>
              </div>
            </CommandEmpty>
          ) : results.length === 0 ? (
            <CommandEmpty className='py-8 text-center text-sm text-muted-foreground'>
              <div className='flex flex-col items-center gap-2'>
                <Icons.search className='h-6 w-6 opacity-40' />
                <p>No results found for &quot;{query}&quot;.</p>
              </div>
            </CommandEmpty>
          ) : (
            Object.entries(grouped).map(([kind, items]) => (
              <CommandGroup key={kind} heading={KIND_LABEL[kind] ?? kind}>
                {items.map((item) => {
                  const KindIcon = KIND_ICONS[kind] ?? Icons.search;
                  return (
                    <CommandItem
                      key={`${item.kind}-${item.id}`}
                      value={`${item.kind}-${item.id}`}
                      onSelect={() => {}}
                      className='flex flex-col items-start gap-1 py-2'
                    >
                      <div className='flex w-full items-center gap-2'>
                        <KindIcon className='h-4 w-4 shrink-0 text-muted-foreground' />
                        <span className='flex-1 truncate text-sm font-medium'>{item.title}</span>
                        <span className='text-xs tabular-nums text-muted-foreground'>
                          score {item.score.toFixed(1)}
                        </span>
                      </div>
                      {item.snippet && (
                        <p className='line-clamp-2 w-full pl-6 text-xs text-muted-foreground'>
                          {item.snippet}
                        </p>
                      )}
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            ))
          )}
        </CommandList>
      </Command>
    </CommandDialog>
  );
}

export function AISearchTrigger({ className }: { className?: string }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type='button'
        onClick={() => setOpen(true)}
        className={cn(
          'inline-flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-input bg-background px-3 text-sm text-muted-foreground shadow-sm hover:bg-accent hover:text-accent-foreground',
          className
        )}
      >
        <span className='flex items-center gap-2'>
          <Icons.sparkles className='h-4 w-4' />
          AI Search...
        </span>
        <span className='hidden text-xs text-muted-foreground/70 md:inline'>⌘K</span>
      </button>
      <AISearch open={open} onOpenChange={setOpen} />
    </>
  );
}
