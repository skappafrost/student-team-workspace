'use client';

import {
  Avatar,
  AvatarFallback,
  AvatarGroup,
  AvatarGroupCount,
  AvatarImage
} from '@/components/ui/avatar';
import { cn } from '@/lib/utils';

export interface AvatarStackUser {
  name: string;
  avatar?: string;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

interface AvatarStackProps {
  users: AvatarStackUser[];
  max?: number;
  size?: 'default' | 'sm' | 'lg';
  className?: string;
}

/** Overlapping avatar stack with a "+N" overflow pill (uiguideline pattern). */
export function AvatarStack({ users, max = 4, size = 'default', className }: AvatarStackProps) {
  const shown = users.slice(0, max);
  const overflow = users.length - shown.length;

  return (
    <AvatarGroup className={className}>
      {shown.map((user) => (
        <Avatar key={user.name} size={size}>
          {user.avatar ? <AvatarImage src={user.avatar} alt={user.name} /> : null}
          <AvatarFallback>{initials(user.name)}</AvatarFallback>
        </Avatar>
      ))}
      {overflow > 0 && <AvatarGroupCount>+{overflow}</AvatarGroupCount>}
    </AvatarGroup>
  );
}
