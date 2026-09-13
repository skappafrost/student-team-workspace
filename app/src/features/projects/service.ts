import { Project, CreateProjectPayload, UpdateProjectPayload } from './types';
import { createApiClient } from '@/lib/api-client';

const apiRequest = createApiClient('/api/projects');


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
