'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Icons } from '@/components/icons';
import { getMembers } from '../api/service';
import { WorkspaceMember } from '../api/types';

interface NewDMDialogProps {
  currentUserId?: string;
  onSubmit: (userId: string) => Promise<unknown>;
  isSubmitting?: boolean;
}

function memberLabel(member: WorkspaceMember): string {
  return member.user?.display_name || member.user?.email || member.user_id;
}

export function NewDMDialog({ currentUserId, onSubmit, isSubmitting }: NewDMDialogProps) {
  const [open, setOpen] = useState(false);

  const membersQuery = useQuery<WorkspaceMember[]>({
    queryKey: ['workspace', 'members'],
    queryFn: getMembers,
    enabled: open
  });

  const others = (membersQuery.data ?? []).filter(
    (m) => (m.user?.id ?? m.user_id) !== currentUserId
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant='ghost' size='sm' className='h-6 gap-1 px-2 text-xs' aria-label='New direct message' />
        }
      >
        <Icons.add className='size-3' />
        New
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>New direct message</DialogTitle>
          <DialogDescription>Pick a workspace member to chat with privately.</DialogDescription>
        </DialogHeader>
        <div className='max-h-64 space-y-1 overflow-y-auto' role='list'>
          {membersQuery.isLoading ? (
            <p className='text-muted-foreground py-4 text-center text-sm'>Loading members…</p>
          ) : others.length === 0 ? (
            <p className='text-muted-foreground py-4 text-center text-sm'>No other members yet.</p>
          ) : (
            others.map((member) => {
              const userId = member.user?.id ?? member.user_id;
              return (
                <button
                  key={userId}
                  type='button'
                  role='listitem'
                  disabled={isSubmitting}
                  onClick={async () => {
                    await onSubmit(userId);
                    setOpen(false);
                  }}
                  className='hover:bg-muted focus-visible:ring-primary/50 flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none'
                >
                  <span className='bg-primary/15 text-primary flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold'>
                    {memberLabel(member).slice(0, 2).toUpperCase()}
                  </span>
                  <span className='text-foreground text-sm font-medium'>
                    {memberLabel(member)}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
