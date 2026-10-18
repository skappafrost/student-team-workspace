/**
 * What `GET /api/workspace/current` is allowed to say, given what the backend did.
 *
 * The handler used to answer every failure with `{ workspace: null }` at HTTP 200,
 * which collapsed three different facts — "you are not signed in", "the backend
 * refused", "this account belongs to no workspace" — into one payload. The only
 * consumer that branches on it is `usePresence`, and it reacts by *disabling*
 * its query (`presenceQueryOptions`'s `enabled: !!workspaceId`), so a backend
 * blip arrived as "presence unavailable" with no error raised anywhere.
 *
 * The rule this file exists to enforce: `404 "No workspace found"` is reserved
 * for the one answer that earns it. Everything the backend did wrong keeps the
 * status the backend gave, or a 5xx that says so — the same shape the honest
 * sibling `api/presence/route.ts` already uses for 401/404.
 *
 * Kept out of the handler so the decision has a test
 * (`tests-unit/current-workspace.test.ts`): a route handler needs `next/headers`
 * and a cookie jar, and `bun test` has neither. That the handler really calls
 * this and the backend really answers that way is `tests/current-workspace.spec.ts`.
 */

/** What the lookup got back. Built by the handler; each branch is a different fact. */
export type WorkspaceLookup =
  /** No `session_token` cookie — there is no identity to resolve a workspace for. */
  | { kind: 'no-session' }
  /** The fetch itself threw: the backend was not answering, not refusing. */
  | { kind: 'unreachable' }
  /** The backend answered a non-2xx. `detail` is its own text when it had any. */
  | { kind: 'refused'; status: number; detail: string | null }
  /** The backend answered 2xx. `rows` is its decoded body, whatever shape that was. */
  | { kind: 'answered'; rows: unknown };

export interface CurrentWorkspace {
  id: string;
  name: string;
}

export type WorkspaceLookupResponse =
  | { status: 200; body: { workspace: CurrentWorkspace } }
  | { status: number; body: { error: string } };

export function currentWorkspaceResponse(lookup: WorkspaceLookup): WorkspaceLookupResponse {
  switch (lookup.kind) {
    case 'no-session':
      return { status: 401, body: { error: 'Not authenticated' } };
    case 'unreachable':
      return { status: 503, body: { error: 'Workspace lookup failed: backend unreachable' } };
    case 'refused':
      // Forwarded rather than folded: a revoked session (401) and a backend
      // crash (500) have to stay tellable apart from the 404 below, or this
      // route is again claiming something about the account it was never told.
      return {
        status: lookup.status,
        body: {
          error: lookup.detail ?? `Workspace lookup failed: backend answered ${lookup.status}`
        }
      };
    case 'answered': {
      if (!Array.isArray(lookup.rows)) {
        // A 200 whose body is not the array `GET /workspaces` documents is a
        // broken contract, not an empty account.
        return {
          status: 502,
          body: { error: 'Workspace lookup failed: unexpected response from backend' }
        };
      }
      if (lookup.rows.length === 0) {
        return { status: 404, body: { error: 'No workspace found' } };
      }
      const workspace = asCurrentWorkspace(lookup.rows[0]);
      if (!workspace) {
        return {
          status: 502,
          body: { error: 'Workspace lookup failed: unexpected response from backend' }
        };
      }
      return { status: 200, body: { workspace } };
    }
  }
}

/**
 * The first row, if it is a row. `id` is the only thing the BFF can act on;
 * `name` is cosmetic and keeps the handler's original fallback.
 */
function asCurrentWorkspace(row: unknown): CurrentWorkspace | null {
  if (typeof row !== 'object' || row === null) return null;
  const { id, name } = row as { id?: unknown; name?: unknown };
  if (typeof id !== 'string' || id.length === 0) return null;
  return { id, name: typeof name === 'string' && name.length > 0 ? name : 'Workspace' };
}
