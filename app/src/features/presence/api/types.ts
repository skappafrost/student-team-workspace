/** Wire contract for `GET /api/presence` and `POST /api/presence/me`. */
export const PRESENCE_STATUSES = ['online', 'away', 'dnd', 'offline'] as const;

export type PresenceStatus = (typeof PRESENCE_STATUSES)[number];

export interface PresenceRow {
  user_id: string;
  name: string | null;
  /** Derived server-side, never stored raw: an `online` row whose `last_seen` is
   *  stale comes back as `away` then `offline`. */
  status: PresenceStatus;
  status_message: string | null;
  /** Naive UTC with no `Z` (see docs/API.md § Conventions). Append `Z` before
   *  `new Date(...)`, or a non-UTC client shifts every timestamp. */
  last_seen: string | null;
}

export interface PresencePatch {
  status: PresenceStatus;
  /** `null` clears the message; omitting the key leaves it unchanged. */
  status_message?: string | null;
}

/** Frame the workspace presence socket pushes. */
export interface PresenceUpdateFrame extends PresenceRow {
  type: 'presence_update';
}
