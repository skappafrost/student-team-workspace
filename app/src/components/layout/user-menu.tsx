'use client';

import * as React from 'react';

import { Icons } from '@/components/icons';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { PresenceDot } from '@/components/ui/presence-dot';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
  PRESENCE_META,
  PRESENCE_STATUSES
} from '@/features/presence/lib/status-meta';
import { usePresence, useSetPresence } from '@/features/presence/hooks/use-presence';
import { signOut, signOutEverywhere, type SessionUser } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';

/**
 * Dashboard user menu (avatar trigger → account info + logout).
 * Logout calls DELETE /api/auth/session (which clears the httpOnly cookie and
 * best-effort hits the backend /auth/logout), then hard-redirects to sign-in.
 */
export function UserMenu({ user }: { user: SessionUser }) {
  const [isPending, startTransition] = React.useTransition();
  const { locale, setLocale, t } = useI18n();
  const { byUser, hidden: presenceHidden } = usePresence();
  const setStatus = useSetPresence();
  const showPresence = !presenceHidden;
  const myStatus = byUser.get(user.id)?.status;

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
          <Button
            variant='ghost'
            size='icon'
            aria-label='Account menu'
            disabled={isPending}
            className='size-8'
          >
            <Avatar size='sm' className='size-8'>
              <AvatarFallback>{(user.name || user.email).slice(0, 2).toUpperCase()}</AvatarFallback>
              {showPresence && myStatus ? <PresenceDot status={myStatus} /> : null}
            </Avatar>
          </Button>
        }
      />
      <DropdownMenuContent align='end' className='w-56'>
        {/* Plain div: DropdownMenuLabel wraps Menu.GroupLabel which requires a
            Menu.Group parent (Base UI error #31 otherwise). */}
        <div className='flex flex-col px-1.5 py-1'>
          <span className='truncate text-sm font-medium'>{user.name || user.email}</span>
          <span className='text-muted-foreground truncate text-xs font-normal'>{user.email}</span>
        </div>
        {showPresence ? (
          <>
            <DropdownMenuSeparator />
            {PRESENCE_STATUSES.map((status) => (
              <DropdownMenuItem
                key={status}
                data-presence-option={status}
                disabled={setStatus.isPending}
                onClick={(event) => {
                  event.preventDefault();
                  setStatus.mutate({ status });
                }}
              >
                {t(PRESENCE_META[status].label)}
                {myStatus === status ? <Icons.check className='ms-auto' /> : null}
              </DropdownMenuItem>
            ))}
          </>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={(event) => {
            event.preventDefault();
            setLocale(locale === 'vi' ? 'en' : 'vi');
          }}
        >
          {t('Language')}: {locale === 'vi' ? 'Tiếng Việt' : 'English'}
        </DropdownMenuItem>
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
          {isPending ? 'Signing out…' : t('Log out')}
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
          {isPending ? 'Signing out…' : t('Sign out everywhere')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
