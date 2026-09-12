export interface MyTask {
  id: string;
  project_id: string;
  assignee_id: string | null;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  position: number;
  due_at: string | null;
  created_at: string;
  updated_at: string;
  project_name: string;
  workspace_name: string;
}

export type DueBucket = 'overdue' | 'today' | 'week' | 'later' | 'none';
