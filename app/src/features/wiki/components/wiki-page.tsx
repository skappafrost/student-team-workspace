'use client';

/**
 * Wiki page shell
 *
 * Sources (zero-native-design rule):
 * - Page layout wrapper: project PageContainer
 * - Two-pane responsive grid: Tailwind CSS grid utilities
 * - Failed-load state: this repo's own error `<Empty>` treatment, as used by
 *   `features/notifications/components/notification-list.tsx`,
 *   `features/files/components/file-list.tsx`,
 *   `features/deadlines/components/deadlines-page.tsx`
 * - Query orchestration: TanStack Query (React Query)
 *   (https://tanstack.com/query/latest)
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/use-debounce';
import {
  pagesQueryOptions,
  pageQueryOptions,
  recentPagesQueryOptions,
  searchPagesQueryOptions
} from '../api/queries';
import { WikiSidebar } from './wiki-sidebar';
import { PageViewer } from './page-viewer';

export default function WikiPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const debouncedSearch = useDebounce(searchQuery, 250);

  const isSearching = debouncedSearch.trim().length > 0;

  const pagesQuery = useQuery(pagesQueryOptions());
  const searchPagesQuery = useQuery(searchPagesQueryOptions(debouncedSearch));
  const recentPagesQuery = useQuery(recentPagesQueryOptions());

  const basePages = pagesQuery.data ?? [];
  const searchResults = searchPagesQuery.data ?? [];
  const displayedPages = isSearching ? searchResults : basePages;
  // Whichever query is on screen is the one that can fail, and a failed one has
  // to say so: falling through to the sidebar would report the refusal as
  // "No pages found.", which is a different claim than the backend made.
  const listQuery = isSearching ? searchPagesQuery : pagesQuery;
  const isLoading = listQuery.isLoading;

  const selectedPageId = useMemo(() => {
    if (selectedId) return selectedId;
    return displayedPages[0]?.id ?? null;
  }, [selectedId, displayedPages.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const pageQuery = useQuery(pageQueryOptions(selectedPageId));

  return (
    <PageContainer pageTitle='Wiki' pageDescription='Browse workspace pages and documentation.'>
      <div
        className={cn(
          'relative grid h-[calc(100dvh-10rem)] w-full gap-3 overflow-hidden rounded-2xl border border-border/50 bg-background/70 p-3 backdrop-blur-xl sm:p-4 lg:grid-cols-[320px_1fr] lg:rounded-3xl'
        )}
      >
        {isLoading ? (
          <div className='flex flex-col gap-4 p-2'>
            <Skeleton className='h-8 w-1/2' />
            <Skeleton className='h-6 w-full' />
            <Skeleton className='h-6 w-full' />
            <Skeleton className='h-6 w-full' />
          </div>
        ) : listQuery.isError ? (
          <Empty className='border py-16'>
            <EmptyHeader>
              <EmptyMedia variant='icon' className='size-12 rounded-full'>
                <Icons.warning className='size-6' />
              </EmptyMedia>
              <EmptyTitle>Failed to load pages</EmptyTitle>
              <EmptyDescription>
                {listQuery.error instanceof Error
                  ? listQuery.error.message
                  : 'Something went wrong.'}
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button variant='outline' size='sm' onClick={() => listQuery.refetch()}>
                Try again
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <WikiSidebar
            pages={displayedPages}
            recentPages={recentPagesQuery.data ?? []}
            selectedId={selectedPageId}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            onSelect={setSelectedId}
          />
        )}

        <div className='min-h-0 flex-1 overflow-hidden rounded-2xl border border-transparent bg-transparent sm:gap-4'>
          <PageViewer
            page={pageQuery.data}
            isLoading={pageQuery.isLoading}
            onSelectPage={setSelectedId}
          />
        </div>
      </div>
    </PageContainer>
  );
}
