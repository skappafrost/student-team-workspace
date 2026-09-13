import { CreateTaskPayload, Task, UpdateTaskPayload } from './types';
import { createApiClient } from '@/lib/api-client';

const apiRequest = createApiClient('/api/tasks');


export async function getTasks(projectId: string): Promise<Task[]> {
  const data = await apiRequest<{ tasks: Task[] }>(`?project_id=${encodeURIComponent(projectId)}`);
  return data.tasks || [];
}

export async function createTask(projectId: string, payload: CreateTaskPayload): Promise<Task> {
  const data = await apiRequest<{ task: Task }>(`?project_id=${encodeURIComponent(projectId)}`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  return data.task;
}

export async function updateTask(taskId: string, payload: UpdateTaskPayload): Promise<Task> {
  const data = await apiRequest<{ task: Task }>('', {
    method: 'PATCH',
    body: JSON.stringify({ taskId, ...payload })
  });
  return data.task;
}

export async function deleteTask(taskId: string): Promise<void> {
  await apiRequest<{ ok: boolean }>(`?taskId=${encodeURIComponent(taskId)}`, {
    method: 'DELETE'
  });
}
