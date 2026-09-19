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

import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import type { WikiPage } from '../api/types';
import { pageBacklinksQueryOptions } from '../api/queries';
import { AISummaryCard } from '@/features/ai/components/ai-summary-card';
import { PageHistorySheet } from './page-history-sheet';

interface PageViewerProps {
  page: WikiPage | null | undefined;
  isLoading?: boolean;
  onSelectPage?: (id: string) => void;
  /** All pages in the workspace, used to resolve [[title]]/[[slug]] wiki links. */
  pages?: WikiLinkTarget[];
}

type WikiLinkTarget = Pick<WikiPage, 'id' | 'slug' | 'title'>;

const WIKI_LINK_RE = /\[\[([^\]]+)\]\]/g;

/**
 * Renders page content with `[[title]]` / `[[slug]]` wiki links as clickable
 * buttons (Notion/Obsidian wiki-link idiom). Unknown targets render muted.
 */
function WikiContent({
  content,
  pages,
  onSelectPage
}: {
  content: string;
  pages: WikiLinkTarget[];
  onSelectPage?: (id: string) => void;
}) {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of content.matchAll(WIKI_LINK_RE)) {
    const idx = match.index ?? 0;
    if (idx > last) nodes.push(content.slice(last, idx));
    const target = match[1].trim().toLowerCase();
    const targetPage = pages.find(
      (p) => p.slug.toLowerCase() === target || p.title.toLowerCase() === target
    );
    if (targetPage) {
      nodes.push(
        <button
          key={`wl-${key++}`}
          type='button'
          onClick={() => onSelectPage?.(targetPage.id)}
          className='text-primary hover:text-primary/80 font-medium underline decoration-dotted underline-offset-2'
        >
          {match[1]}
        </button>
      );
    } else {
      nodes.push(
        <span key={`wl-${key++}`} className='text-muted-foreground italic'>
          {match[0]}
        </span>
      );
    }
    last = idx + match[0].length;
  }
  if (last < content.length) nodes.push(content.slice(last));
  return <>{nodes}</>;
}

export function PageViewer({ page, isLoading, onSelectPage, pages = [] }: PageViewerProps) {
  const backlinksQuery = useQuery(pageBacklinksQueryOptions(page?.id ?? null));
  const backlinks = backlinksQuery.data ?? [];
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
        <div className='flex items-start justify-between gap-2'>
          <div className='space-y-1.5'>
            <CardTitle className='text-base sm:text-lg'>{page.title}</CardTitle>
            <CardDescription>Slug: {page.slug}</CardDescription>
          </div>
          <PageHistorySheet page={page} />
        </div>
      </CardHeader>
      <ScrollArea className='flex-1'>
        <CardContent className='py-4'>
          <article className='prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap'>
            {page.content ? (
              <WikiContent content={page.content} pages={pages} onSelectPage={onSelectPage} />
            ) : (
              <span className='italic text-muted-foreground'>No content.</span>
            )}
          </article>
        </CardContent>
      </ScrollArea>
      {backlinks.length > 0 && (
        <div className='shrink-0 border-t px-4 py-3'>
          <p className='text-muted-foreground mb-2 text-xs font-medium uppercase tracking-wide'>
            Linked from
          </p>
          <div className='flex flex-wrap gap-1.5'>
            {backlinks.map((b) => (
              <button
                key={b.id}
                type='button'
                onClick={() => onSelectPage?.(b.id)}
                className='bg-muted/60 hover:bg-muted rounded-md px-2 py-1 text-xs'
              >
                {b.title}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className='shrink-0 border-t p-4'>
        <AISummaryCard kind='page' refId={page.id} title='Summarize page' />
      </div>
    </Card>
  );
}
