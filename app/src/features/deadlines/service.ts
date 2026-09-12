import { MyTask } from './types';

export async function getMyTasks(): Promise<MyTask[]> {
  const res = await fetch('/api/tasks/mine', { credentials: 'include' });
  const data = (await res.json().catch(() => ({}))) as {
    tasks?: MyTask[];
    error?: string;
  };
  if (!res.ok) {
    throw new Error(data.error || `API error: ${res.status}`);
  }
  return data.tasks || [];
}
