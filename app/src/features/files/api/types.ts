export interface FileRecord {
  id: string;
  workspace_id: string;
  project_id?: string | null;
  task_id?: string | null;
  message_id?: string | null;
  name: string;
  type: string;
  size: number;
  url: string;
  uploaded_by: string;
  created_at: string;
}

export interface UploadFilePayload {
  file: File;
}
