import { FileRecord } from './types';

const API_BASE = '/api/files';

async function apiRequest<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    credentials: 'include'
  });

  if (!res.ok) {
    const data = (await res.json().catch(() => ({ error: 'Request failed' }))) as {
      error?: string;
    };
    throw new Error(data.error || `API error: ${res.status}`);
  }

  return res.json() as Promise<T>;
}

export async function getFiles(): Promise<FileRecord[]> {
  const data = await apiRequest<{ files: FileRecord[] }>('');
  return data.files || [];
}

export async function uploadFile(payload: { file: File }): Promise<FileRecord> {
  const formData = new FormData();
  formData.append('file', payload.file);

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

export async function downloadFile(file: FileRecord): Promise<void> {
  const res = await fetch(file.url, {
    credentials: 'include'
  });

  if (!res.ok) {
    throw new Error(`Download failed: ${res.status}`);
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
