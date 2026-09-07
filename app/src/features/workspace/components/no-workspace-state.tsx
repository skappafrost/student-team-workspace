'use client';

import Link from 'next/link';
import { buttonVariants } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';

interface NoWorkspaceStateProps {
  title?: string;
  description?: string;
}

export function NoWorkspaceState({
  title = 'No workspace yet',
  description = 'Create or join a workspace to unlock this feature.'
}: NoWorkspaceStateProps) {
  return (
    <div className='flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-border/60 bg-background/50 p-8 text-center backdrop-blur-xl'>
      <div className='bg-muted/60 mb-4 flex h-16 w-16 items-center justify-center rounded-full'>
        <Icons.workspace className='text-muted-foreground h-8 w-8' />
      </div>
      <h3 className='text-foreground text-lg font-semibold'>{title}</h3>
      <p className='text-muted-foreground mt-2 max-w-sm text-sm'>{description}</p>
      <Link href='/dashboard/settings' className={cn(buttonVariants(), 'mt-6 inline-flex gap-2')}>
        <Icons.settings className='h-4 w-4' />
        Workspace settings
      </Link>
    </div>
  );
}
