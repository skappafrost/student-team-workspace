'use client';

/**
 * Wiki page shell
 *
 * Sources (zero-native-design rule):
 * - Page layout wrapper: project PageContainer
 * - Two-pane responsive grid: Tailwind CSS grid utilities
 * - Query orchestration: TanStack Query (React Query)
 *   (https://tanstack.com/query/latest)
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
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
  const isLoading = isSearching ? searchPagesQuery.isLoading : pagesQuery.isLoading;

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
