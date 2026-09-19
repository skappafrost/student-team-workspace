import { PRESENCE_STATUSES, type PresenceStatus } from '../api/types';

export { PRESENCE_STATUSES };
export type { PresenceStatus };

/**
 * status -> what it looks like and what it says.
 *
 * The shape of this table (state -> label, state -> indicator, plus a tooltip
 * under the dot rather than instead of it) is taken from element-web's
 * `PresenceIconView` switch tables. That project is AGPL, so this is a re-expression
 * from scratch: no code, no DOM, no class names shared. See
 * `design-references/catalogs/usages.json`, record `chat-collab__element-web`.
 *
 * Color is never the only carrier: `label` feeds the tooltip and the accessible
 * name, which is what makes the dot acceptable for a color-blind reader and for
 * the 10 other themes whose palettes differ.
 */
export const PRESENCE_META: Record<PresenceStatus, { label: string; dotClass: string }> = {
  online: { label: 'Online', dotClass: 'bg-presence-online' },
  away: { label: 'Away', dotClass: 'bg-presence-away' },
  dnd: { label: 'Do not disturb', dotClass: 'bg-presence-dnd' },
  offline: { label: 'Offline', dotClass: 'bg-presence-offline' }
};
