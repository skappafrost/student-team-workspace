export interface WikiPage {
  id: string;
  workspace_id: string;
  parent_id: string | null;
  title: string;
  slug: string;
  content: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface WikiPageSummary {
  id: string;
  parent_id: string | null;
  title: string;
  slug: string;
}
