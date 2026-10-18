/**
 * Which of the four things an inbox can honestly say.
 *
 * The order is the whole point: a failed fetch must lose to nothing, because a
 * list that decides between `error` and `empty` in the wrong order reports "the
 * server refused" as "nothing has happened to you". Written once, here, so the
 * precedence has a test (`tests-unit/inbox-state.test.ts`) rather than living in
 * the nesting of one component's JSX.
 */
export type InboxState = 'loading' | 'error' | 'empty' | 'list';

export function inboxState({
  isPending,
  isError,
  count
}: {
  isPending: boolean;
  isError: boolean;
  count: number;
}): InboxState {
  if (isPending) return 'loading';
  if (isError) return 'error';
  return count === 0 ? 'empty' : 'list';
}
