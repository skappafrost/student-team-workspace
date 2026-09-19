import { createApiClient } from '@/lib/api-client';

import type { PresencePatch, PresenceRow } from './types';

const apiRequest = createApiClient('/api/presence');

/** Whole roster, one request: the endpoint is unpaginated by contract. */
export function getWorkspacePresence(): Promise<PresenceRow[]> {
  return apiRequest<PresenceRow[]>('');
}

export function setMyPresence(patch: PresencePatch): Promise<PresenceRow> {
  return apiRequest<PresenceRow>('/me', {
    method: 'POST',
    body: JSON.stringify(patch)
  });
}
