'use client';

/**
 * AI Summary Card
 *
 * Sources (zero-native-design rule):
 * - Card shell + header: shadcn/ui Card
 *   (https://ui.shadcn.com/docs/components/card)
 * - Skeleton loading state: shadcn/ui Skeleton
 *   (https://ui.shadcn.com/docs/components/skeleton)
 * - Button trigger + error state: shadcn/ui Button + Alert
 *   (https://ui.shadcn.com/docs/components/button)
 */

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Icons } from '@/components/icons';
import { summarize } from '../api/service';
import { cn } from '@/lib/utils';

interface AISummaryCardProps {
  kind: 'task' | 'page' | 'channel';
  refId: string;
  title?: string;
  className?: string;
}

export function AISummaryCard({ kind, refId, title, className }: AISummaryCardProps) {
  const [summary, setSummary] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => summarize({ kind, ref_id: refId }),
    onSuccess: (data) => {
      setSummary(data);
    }
  });

  const isIdle = !mutation.isPending && !mutation.isError && summary === null;
  const isEmpty = summary === '';

  return (
    <Card className={cn('gap-3', className)}>
      <CardHeader className='pb-0'>
        <CardTitle className='flex items-center gap-2 text-sm'>
          <Icons.sparkles className='h-4 w-4 text-primary' />
          {title || 'AI Summary'}
        </CardTitle>
        <CardDescription className='text-xs'>
          Generate a quick summary powered by AI.
        </CardDescription>
      </CardHeader>

      <CardContent className='space-y-3'>
        {mutation.isPending && (
          <div className='space-y-2'>
            <Skeleton className='h-4 w-full' />
            <Skeleton className='h-4 w-5/6' />
            <Skeleton className='h-4 w-4/6' />
          </div>
        )}

        {mutation.isError && (
          <div className='rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive'>
            {mutation.error?.message || 'Failed to generate summary.'}
          </div>
        )}

        {!mutation.isPending && !mutation.isError && summary !== null && (
          <p
            className={cn(
              'whitespace-pre-wrap text-sm leading-relaxed',
              isEmpty && 'italic text-muted-foreground'
            )}
          >
            {isEmpty ? 'No content available to summarize.' : summary}
          </p>
        )}

        {isIdle && (
          <Button variant='outline' size='sm' className='w-full' onClick={() => mutation.mutate()}>
            <Icons.sparkles className='mr-2 h-4 w-4' />
            Summarize
          </Button>
        )}

        {!isIdle && !mutation.isPending && summary !== null && (
          <Button variant='ghost' size='sm' className='w-full' onClick={() => mutation.mutate()}>
            <Icons.sparkles className='mr-2 h-4 w-4' />
            Regenerate
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
