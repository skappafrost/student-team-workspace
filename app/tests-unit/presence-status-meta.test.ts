/**
 * `PRESENCE_META` is indexed as `PRESENCE_META[status].label` with no fallback
 * (`src/components/layout/user-menu.tsx:93`, `src/components/ui/presence-dot.tsx:32`)
 * and `status` arrives off the wire, so a status the registry does not have is a
 * crash at render. `Record<PresenceStatus, …>` catches a missing entry for a
 * status already in the union; it cannot say anything about a payload the union
 * has not caught up with, nor about the class names. The same table is where the
 * CI CSS grep's class names come from.
 *
 * This is the cheap half of that contract — the registry stays complete and
 * self-consistent. That the utilities exist in the *compiled* CSS is the other
 * half, still owned by the grep step in `.github/workflows/ci.yml`; a passing
 * suite here does not mean the dot renders.
 */
import { describe, expect, it } from 'bun:test';

import { PRESENCE_META, PRESENCE_STATUSES } from '@/features/presence/lib/status-meta';

describe('PRESENCE_META', () => {
  it('has exactly one entry per status the backend can send', () => {
    expect(Object.keys(PRESENCE_META).toSorted()).toEqual(PRESENCE_STATUSES.toSorted());
  });

  it('names the dot utility after the status, which is what the CI grep looks for', () => {
    for (const status of PRESENCE_STATUSES) {
      expect(PRESENCE_META[status].dotClass).toBe(`bg-presence-${status}`);
    }
  });

  it('gives every status a distinct label, so color is never the only carrier', () => {
    const labels = PRESENCE_STATUSES.map((status) => PRESENCE_META[status].label);
    for (const label of labels) {
      expect(label.trim()).not.toBe('');
    }
    expect(new Set(labels).size).toBe(PRESENCE_STATUSES.length);
    // the one that has to spell itself out: a dot alone cannot say "do not disturb"
    expect(PRESENCE_META.dnd.label).toBe('Do not disturb');
  });
});
