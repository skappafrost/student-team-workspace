import { Project, CreateProjectPayload, UpdateProjectPayload } from './types';

async function apiRequest<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api/projects${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string>)
    },
    credentials: 'include'
  });
  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) {
    throw new Error(data.error || `API error: ${res.status}`);
  }
  return data;
}

export async function getProjects(): Promise<Project[]> {
  const data = await apiRequest<{ projects: Project[] }>('');
  return data.projects || [];
}

export async function createProject(payload: CreateProjectPayload): Promise<Project> {
  const data = await apiRequest<{ project: Project }>('', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  return data.project;
}

export async function updateProject(id: string, payload: UpdateProjectPayload): Promise<Project> {
  const data = await apiRequest<{ project: Project }>('', {
    method: 'PATCH',
    body: JSON.stringify({ projectId: id, ...payload })
  });
  return data.project;
}

export async function deleteProject(id: string): Promise<void> {
  await apiRequest<void>(`?projectId=${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });
}
