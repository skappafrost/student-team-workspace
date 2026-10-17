import { FileRecord } from './types';
import { createApiClient } from '@/lib/api-client';

const API_BASE = '/api/files';

const apiRequest = createApiClient(API_BASE, { jsonHeaders: false });

export interface FileLinkFilter {
  project_id?: string;
  task_id?: string;
  message_id?: string;
}

export async function getFiles(filter?: FileLinkFilter): Promise<FileRecord[]> {
  const params = new URLSearchParams();
  if (filter?.project_id) params.set('project_id', filter.project_id);
  if (filter?.task_id) params.set('task_id', filter.task_id);
  if (filter?.message_id) params.set('message_id', filter.message_id);
  const suffix = params.size > 0 ? `?${params.toString()}` : '';
  const data = await apiRequest<{ files: FileRecord[] }>(suffix);
  return data.files || [];
}

export async function uploadFile(payload: {
  file: File;
  project_id?: string;
  task_id?: string;
  message_id?: string;
}): Promise<FileRecord> {
  const formData = new FormData();
  formData.append('file', payload.file);
  if (payload.project_id) formData.append('project_id', payload.project_id);
  if (payload.task_id) formData.append('task_id', payload.task_id);
  if (payload.message_id) formData.append('message_id', payload.message_id);

  const res = await fetch(API_BASE, {
    method: 'POST',
    body: formData,
    credentials: 'include'
  });

  if (!res.ok) {
    const data = (await res.json().catch(() => ({ error: 'Upload failed' }))) as { error?: string };
    throw new Error(data.error || `Upload failed: ${res.status}`);
  }

  return res.json() as Promise<FileRecord>;
}

export async function updateFile(
  id: string,
  payload: {
    name?: string;
    project_id?: string | null;
    task_id?: string | null;
    message_id?: string | null;
  }
): Promise<FileRecord> {
  return apiRequest<FileRecord>(`/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export async function deleteFile(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    credentials: 'include'
  });

  if (!res.ok) {
    const data = (await res.json().catch(() => ({ error: 'Delete failed' }))) as { error?: string };
    throw new Error(data.error || `Delete failed: ${res.status}`);
  }
}

/** The app-relative URL for a file's bytes.
 *
 * `file.url` is `/uploads/{storage_key}` as emitted by the backend, which is a
 * path on the *backend's* origin; the browser resolves it against the Next origin,
 * where it is served by the BFF proxy at `api/uploads/[key]`. Prefixing `/api`
 * keeps the backend's value authoritative (its shape is pinned by the file tests)
 * while pointing the browser at a route that exists.
 */
export const fileAssetUrl = (file: FileRecord): string => `/api${file.url}`;

export async function downloadFile(file: FileRecord): Promise<void> {
  const res = await fetch(fileAssetUrl(file), {
    credentials: 'include'
  });

  if (!res.ok) {
    // Surface the server's reason: after the private-channel rule, a 403 here
    // means "this file belongs to a channel you are not in", and "Download
    // failed: 403" would hide that from the one person who can act on it.
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || data.detail || `Download failed: ${res.status}`);
  }

  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = file.name;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}

export function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** i;
  return `${value.toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
}
