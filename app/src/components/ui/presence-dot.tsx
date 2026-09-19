'use client';

import { AvatarBadge } from '@/components/ui/avatar';
import { PRESENCE_META, type PresenceStatus } from '@/features/presence/lib/status-meta';
import { cn } from '@/lib/utils';

/**
 * A presence status dot.
 *
 * Positioning, sizing and the background ring all come from `AvatarBadge`
 * (`components/ui/avatar.tsx`), a registered shadcn/ui primitive that was
 * already vendored and unused — so no geometry is authored here, which is what
 * the Zero Native Design Rule requires. It needs a `<Avatar>` ancestor, which
 * supplies both `relative` and the `group/avatar` scope its size variants read.
 *
 * Two deliberate overrides of the primitive's own classes:
 * - `bg-blend-normal`, because the shipped badge is meant to sit over an avatar
 *   image with a tinted blend; a status color has to be the actual color.
 * - the `bg-*` itself, per status, from `PRESENCE_META`.
 *
 * The status is also exposed as text (`aria-label` + `title`), because color is
 * not something every reader can use, and the palette differs across the 11
 * themes.
 */
export function PresenceDot({
  status,
  className
}: {
  status: PresenceStatus;
  className?: string;
}) {
  const meta = PRESENCE_META[status];
  return (
    <AvatarBadge
      data-status={status}
      role='img'
      aria-label={meta.label}
      title={meta.label}
      className={cn('bg-blend-normal', meta.dotClass, className)}
    />
  );
}
