'use client';

/**
 * Page viewer / content pane
 *
 * Sources (zero-native-design rule):
 * - Card shell + header: shadcn/ui Card
 *   (https://ui.shadcn.com/docs/components/card) — based on Base UI primitives
 * - Scrollable body: shadcn/ui ScrollArea
 *   (https://ui.shadcn.com/docs/components/scroll-area)
 * - Skeleton loading state: shadcn/ui Skeleton
 *   (https://ui.shadcn.com/docs/components/skeleton)
 * - Markdown editor placeholder: @uiw/react-md-editor (documented; to be wired in W6-3)
 *   (https://github.com/uiwjs/react-md-editor)
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import type { WikiPage } from '../api/types';
import { AISummaryCard } from '@/features/ai/components/ai-summary-card';

interface PageViewerProps {
  page: WikiPage | null | undefined;
  isLoading?: boolean;
}

export function PageViewer({ page, isLoading }: PageViewerProps) {
  if (isLoading) {
    return (
      <Card className='h-full overflow-hidden'>
        <CardHeader className='space-y-2'>
          <Skeleton className='h-6 w-1/2' />
          <Skeleton className='h-4 w-1/3' />
        </CardHeader>
        <CardContent className='space-y-3'>
          <Skeleton className='h-4 w-full' />
          <Skeleton className='h-4 w-5/6' />
          <Skeleton className='h-4 w-4/5' />
        </CardContent>
      </Card>
    );
  }

  if (!page) {
    return (
      <Card className='flex h-full flex-col items-center justify-center text-center'>
        <CardHeader>
          <CardTitle className='text-base'>Select a page</CardTitle>
          <CardDescription>Choose a page from the tree to view its content.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card className='flex h-full flex-col overflow-hidden'>
      <CardHeader className='shrink-0 border-b'>
        <CardTitle className='text-base sm:text-lg'>{page.title}</CardTitle>
        <CardDescription>Slug: {page.slug}</CardDescription>
      </CardHeader>
      <ScrollArea className='flex-1'>
        <CardContent className='py-4'>
          <article className='prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap'>
            {page.content || <span className='italic text-muted-foreground'>No content.</span>}
          </article>
        </CardContent>
      </ScrollArea>
      <div className='shrink-0 border-t p-4'>
        <AISummaryCard kind='page' refId={page.id} title='Summarize page' />
      </div>
    </Card>
  );
}
