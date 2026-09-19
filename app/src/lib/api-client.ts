/**
 * A failed BFF call, with the HTTP status attached.
 *
 * Callers need the status, not prose: "am I a guest, so presence is refused" and
 * "did the network die" have to be told apart, and matching on the message text
 * is how a 403 ends up rendered as a retrying error banner.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Shared BFF fetch wrapper (R04) — replaces per-feature apiRequest copies.
 *
 * const apiRequest = createApiClient('/api/tasks');
 * const data = await apiRequest<{ tasks: Task[] }>('?project_id=…');
 */
export function createApiClient(basePath: string, opts?: { jsonHeaders?: boolean }) {
  const jsonHeaders = opts?.jsonHeaders !== false;
  return async function apiRequest<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${basePath}${endpoint}`, {
      ...options,
      headers: {
        ...(jsonHeaders ? { 'Content-Type': 'application/json' } : {}),
        ...(options?.headers as Record<string, string>)
      },
      credentials: 'include'
    });

    const data = (await res.json().catch(() => ({}))) as T & {
      error?: string;
      detail?: string;
    };
    if (!res.ok) {
      throw new ApiError(data.error || data.detail || `API error: ${res.status}`, res.status);
    }
    return data;
  };
}
