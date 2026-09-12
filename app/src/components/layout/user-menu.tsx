'use client';

import * as React from 'react';

import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { signOut, signOutEverywhere, type SessionUser } from '@/lib/auth';

/**
 * Dashboard user menu (avatar trigger → account info + logout).
 * Logout calls DELETE /api/auth/session (which clears the httpOnly cookie and
 * best-effort hits the backend /auth/logout), then hard-redirects to sign-in.
 */
export function UserMenu({ user }: { user: SessionUser }) {
  const [isPending, startTransition] = React.useTransition();

  const handleSignOut = () => {
    void (async () => {
      await signOut();
      // Full navigation so server components re-render without the session.
      window.location.assign('/auth/sign-in');
    })();
    // Mark the UI busy immediately so double-clicks can't fire twice.
    startTransition(() => {});
  };

  const handleSignOutEverywhere = () => {
    void (async () => {
      await signOutEverywhere();
      window.location.assign('/auth/sign-in');
    })();
    startTransition(() => {});
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant='ghost' size='icon' aria-label='Account menu' disabled={isPending}>
            <Icons.account className='size-5' />
          </Button>
        }
      >
        <Icons.account className='size-5' />
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className='w-56'>
        {/* Plain div: DropdownMenuLabel wraps Menu.GroupLabel which requires a
            Menu.Group parent (Base UI error #31 otherwise). */}
        <div className='flex flex-col px-1.5 py-1'>
          <span className='truncate text-sm font-medium'>{user.name || user.email}</span>
          <span className='text-muted-foreground truncate text-xs font-normal'>{user.email}</span>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant='destructive'
          disabled={isPending}
          onClick={(event) => {
            event.preventDefault();
            handleSignOut();
          }}
        >
          <Icons.logout />
          {isPending ? 'Signing out…' : 'Log out'}
        </DropdownMenuItem>
        <DropdownMenuItem
          variant='destructive'
          disabled={isPending}
          onClick={(event) => {
            event.preventDefault();
            handleSignOutEverywhere();
          }}
        >
          <Icons.logout />
          {isPending ? 'Signing out…' : 'Sign out everywhere'}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
