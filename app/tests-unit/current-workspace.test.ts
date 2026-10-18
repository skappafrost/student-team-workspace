/**
 * `currentWorkspaceResponse` is the mapping from "what the backend did" to
 * "what the BFF may claim". The defect it replaces is a fold: `GET
 * /api/workspace/current` answered `{ workspace: null }` at HTTP 200 for a
 * missing session, a refused request and an empty list alike, so the one
 * consumer that branches on it — `usePresence`, which switches its query off
 * when there is no workspace id — read a backend blip as "this account has no
 * workspace" and reported nothing. These assertions are the part a DOM-less
 * runner can pin; that the handler actually applies them against a live backend
 * is `app/tests/current-workspace.spec.ts`, run by `frontend-e2e`.
 */
import { describe, expect, it } from 'bun:test';

import {
  currentWorkspaceResponse,
  type WorkspaceLookup
} from '@/features/workspace/lib/current-workspace';

describe('currentWorkspaceResponse', () => {
  it('answers a first row as the current workspace', () => {
    expect(
      currentWorkspaceResponse({ kind: 'answered', rows: [{ id: 'w1', name: 'Alpha' }] })
    ).toEqual({ status: 200, body: { workspace: { id: 'w1', name: 'Alpha' } } });
  });

  it('takes the first row of the ordered list and never a later one', () => {
    // The BFF's whole notion of "current" is `[0]`; the backend orders it.
    expect(
      currentWorkspaceResponse({
        kind: 'answered',
        rows: [{ id: 'w1' }, { id: 'w2' }]
      })
    ).toEqual({ status: 200, body: { workspace: { id: 'w1', name: 'Workspace' } } });
  });

  it('keeps a row with no name usable', () => {
    expect(currentWorkspaceResponse({ kind: 'answered', rows: [{ id: 'w1' }] })).toEqual({
      status: 200,
      body: { workspace: { id: 'w1', name: 'Workspace' } }
    });
  });

  it('reserves 404 "No workspace found" for the empty list the backend actually returned', () => {
    expect(currentWorkspaceResponse({ kind: 'answered', rows: [] })).toEqual({
      status: 404,
      body: { error: 'No workspace found' }
    });
  });

  it('forwards the backend status when it refuses, instead of claiming an empty account', () => {
    expect(
      currentWorkspaceResponse({
        kind: 'refused',
        status: 401,
        detail: 'Could not validate credentials'
      })
    ).toEqual({ status: 401, body: { error: 'Could not validate credentials' } });
    expect(currentWorkspaceResponse({ kind: 'refused', status: 500, detail: null })).toEqual({
      status: 500,
      body: { error: 'Workspace lookup failed: backend answered 500' }
    });
  });

  it('answers a session-less request as unauthenticated, the sibling api/presence already does', () => {
    expect(currentWorkspaceResponse({ kind: 'no-session' })).toEqual({
      status: 401,
      body: { error: 'Not authenticated' }
    });
  });

  it('answers a backend that never replied as a server-side failure, not a 404', () => {
    expect(currentWorkspaceResponse({ kind: 'unreachable' })).toEqual({
      status: 503,
      body: { error: 'Workspace lookup failed: backend unreachable' }
    });
  });

  it('answers a 200 whose body is not the documented array as a bad gateway', () => {
    for (const rows of [null, undefined, {}, 'workspaces', 42]) {
      expect(currentWorkspaceResponse({ kind: 'answered', rows }).status).toBe(502);
    }
  });

  it('refuses to invent a workspace from a row without an id', () => {
    for (const rows of [[{}], [{ name: 'Alpha' }], [null], ['w1']]) {
      expect(currentWorkspaceResponse({ kind: 'answered', rows }).status).toBe(502);
    }
  });

  it('gives no failure path the answer that means "this account has no workspace"', () => {
    // The one-sentence statement of the bug: `404` used to be reachable from
    // every branch at HTTP 200. Only an empty list earns it.
    const failures: WorkspaceLookup[] = [
      { kind: 'no-session' },
      { kind: 'unreachable' },
      { kind: 'refused', status: 401, detail: null },
      { kind: 'refused', status: 403, detail: 'Forbidden' },
      { kind: 'refused', status: 502, detail: null },
      { kind: 'answered', rows: null },
      { kind: 'answered', rows: {} }
    ];
    for (const lookup of failures) {
      const { status, body } = currentWorkspaceResponse(lookup);
      expect(status === 200).toBe(false);
      expect(body).not.toBeUndefined();
      expect((body as { workspace?: unknown }).workspace).toBeUndefined();
    }
    expect(
      failures
        .filter((f) => f.kind !== 'answered')
        .map((f) => currentWorkspaceResponse(f).status)
        .includes(404)
    ).toBe(false);
  });
});
