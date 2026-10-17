/**
 * The shared `formatDate`. It has one caller today —
 * `src/components/ui/table/data-table-date-filter.tsx` — while
 * `src/components/ui/notification-card.tsx:32` and
 * `src/features/files/components/file-list.tsx:28` each define a local one, so
 * a fix here does not travel. The behaviour worth pinning is the one that
 * cannot be seen at a glance: an unparseable value returns `''` rather than
 * throwing or printing "Invalid Date", because the `try/catch` swallows Intl's
 * RangeError — a bad timestamp disappears quietly instead of failing loud.
 *
 * The assertions pass `timeZone: 'UTC'` explicitly. Without it the rendered
 * date follows the machine's local zone, and a suite whose result depends on
 * where it was run is not a gate.
 */
import { describe, expect, it } from 'bun:test';

import { formatDate } from '@/lib/format';

describe('formatDate', () => {
  it('renders the month/day/year default in UTC', () => {
    expect(formatDate('2026-01-15T00:00:00Z', { timeZone: 'UTC' })).toBe('January 15, 2026');
    expect(formatDate(Date.UTC(2026, 0, 15), { timeZone: 'UTC' })).toBe('January 15, 2026');
  });

  it('lets options override the defaults instead of only adding to them', () => {
    expect(formatDate('2026-01-15T00:00:00Z', { timeZone: 'UTC', month: '2-digit' })).toBe(
      '01/15/2026'
    );
  });

  it('returns the empty string for anything it cannot render', () => {
    expect(formatDate(undefined)).toBe('');
    expect(formatDate('')).toBe('');
    expect(formatDate('not a date')).toBe('');
    // not asserted, because it is engine behaviour rather than this helper's:
    // an out-of-range ISO string is *parseable*, so it never reaches the catch
    // — `formatDate('2026-02-30')` rolls over to "March 2, 2026".
  });

  it('treats epoch 0 as "no date" — the falsy guard does not distinguish it', () => {
    expect(formatDate(0)).toBe('');
  });
});
