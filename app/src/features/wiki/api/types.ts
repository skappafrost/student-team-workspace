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

export interface WikiPageVersion {
  id: string;
  page_id: string;
  version: number;
  title: string;
  content: string | null;
  author_id: string | null;
  author_name: string | null;
  created_at: string;
}
