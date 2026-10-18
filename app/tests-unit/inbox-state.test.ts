/**
 * `inboxState` is the precedence between "loading", "the server refused", "you
 * have nothing" and "here is the list". Getting that order wrong is the defect:
 * a failed fetch that falls through to the empty branch tells someone their
 * inbox is quiet when the backend never answered, which is what the header bell
 * did while it read a store seeded with rows invented in source.
 *
 * A component decides this by nesting, so the decision moved here — the part a
 * DOM-less runner can pin. That the bell draws the matching markup is
 * `app/tests/no-invented-data.spec.ts`, run by the `frontend-e2e` job against a
 * live backend; a green suite here does not prove anything renders.
 */
import { describe, expect, it } from 'bun:test';

import { inboxState } from '@/features/notifications/lib/inbox-state';

describe('inboxState', () => {
  it('says loading while the first fetch is in flight', () => {
    expect(inboxState({ isPending: true, isError: false, count: 0 })).toBe('loading');
  });

  it('prefers error over empty, the swap this replaces', () => {
    expect(inboxState({ isPending: false, isError: true, count: 0 })).toBe('error');
  });

  it('keeps a genuinely empty inbox distinct from a refused one', () => {
    expect(inboxState({ isPending: false, isError: false, count: 0 })).toBe('empty');
  });

  it('reports an error even when stale rows are still in the cache', () => {
    // React Query keeps `data` through a refetch that fails, so `count` can be
    // non-zero while `isError` is true; the failure is what the reader needs.
    expect(inboxState({ isPending: false, isError: true, count: 5 })).toBe('error');
    expect(inboxState({ isPending: false, isError: false, count: 5 })).toBe('list');
  });
});
