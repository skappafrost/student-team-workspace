'use client';

/**
 * Page tree sidebar
 *
 * Sources (zero-native-design rule):
 * - Tree structure + disclosure chevrons: shadcn/ui Collapsible
 *   (https://ui.shadcn.com/docs/components/collapsible) — wrapped around Base UI primitives in src/components/ui/collapsible.tsx
 * - Scrollable list: shadcn/ui ScrollArea
 *   (https://ui.shadcn.com/docs/components/scroll-area) — wrapped around Base UI primitives in src/components/ui/scroll-area.tsx
 * - Icons: Tabler Icons via the centralized Icons registry in src/components/icons.tsx
 */

import { useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { Icons } from '@/components/icons';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { WikiPageSummary } from '../api/types';

function buildPageMap(pages: WikiPageSummary[]) {
  const root: WikiPageSummary[] = [];
  const byParent = new Map<string, WikiPageSummary[]>();

  for (const page of pages) {
    if (page.parent_id) {
      const siblings = byParent.get(page.parent_id) || [];
      siblings.push(page);
      byParent.set(page.parent_id, siblings);
    } else {
      root.push(page);
    }
  }

  return { root, byParent };
}

interface PageTreeNodeProps {
  page: WikiPageSummary;
  pages: WikiPageSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  depth: number;
}

function PageTreeNode({ page, pages, selectedId, onSelect, depth }: PageTreeNodeProps) {
  const children = useMemo(() => pages.filter((p) => p.parent_id === page.id), [pages, page.id]);
  const hasChildren = children.length > 0;
  const [open, setOpen] = useState(true);

  const label = (
    <button
      type='button'
      onClick={() => onSelect(page.id)}
      className={cn(
        'flex min-w-0 flex-1 items-center gap-2 rounded-md py-1.5 pr-2 text-left text-sm transition-colors',
        selectedId === page.id
          ? 'bg-accent text-accent-foreground'
          : 'text-foreground hover:bg-muted hover:text-foreground'
      )}
      style={{ paddingLeft: `${depth * 12 + 8}px` }}
    >
      <Icons.page className='size-4 shrink-0 text-muted-foreground' />
      <span className='truncate'>{page.title}</span>
    </button>
  );

  if (!hasChildren) {
    return <div className='flex items-center'>{label}</div>;
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className='flex items-center'>
        <CollapsibleTrigger
          className='flex size-7 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground'
          onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
            e.stopPropagation();
            setOpen((v) => !v);
          }}
          aria-label={open ? 'Collapse' : 'Expand'}
          style={{ marginLeft: `${depth * 12}px` }}
        >
          <Icons.chevronRight
            className={cn('size-3.5 transition-transform duration-200', open && 'rotate-90')}
          />
        </CollapsibleTrigger>
        {label}
      </div>
      <CollapsibleContent className='overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down'>
        <div className='flex flex-col'>
          {children.map((child) => (
            <PageTreeNode
              key={child.id}
              page={child}
              pages={pages}
              selectedId={selectedId}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

interface PageTreeProps {
  pages: WikiPageSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  className?: string;
}

export function PageTree({ pages, selectedId, onSelect, className }: PageTreeProps) {
  const { root } = useMemo(() => buildPageMap(pages), [pages]);

  return (
    <div
      className={cn(
        'border-border/50 bg-background/70 flex h-full flex-col overflow-hidden rounded-2xl border backdrop-blur-xl',
        className
      )}
    >
      <div className='border-b px-3 py-2.5 font-medium text-sm'>Pages</div>
      <ScrollArea className='flex-1 px-2 py-2'>
        {pages.length === 0 ? (
          <div className='px-2 py-4 text-center text-sm text-muted-foreground'>No pages yet.</div>
        ) : (
          <div className='flex flex-col gap-0.5'>
            {root.map((page) => (
              <PageTreeNode
                key={page.id}
                page={page}
                pages={pages}
                selectedId={selectedId}
                onSelect={onSelect}
                depth={0}
              />
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
