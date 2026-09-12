export interface ActivityItem {
  id: string;
  workspace_id: string;
  actor_id: string;
  actor_name: string;
  verb: string;
  target_type: string;
  target_id: string;
  target_label: string | null;
  created_at: string;
}
