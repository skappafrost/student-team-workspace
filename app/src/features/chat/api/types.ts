export type ChannelType = 'general' | 'project' | 'private';

export interface Channel {
  id: string;
  workspace_id: string;
  name: string;
  type: ChannelType;
  created_by: string;
  is_private: boolean;
  created_at: string;
}

export interface Message {
  id: string;
  channel_id: string;
  author_id: string;
  author_name?: string | null;
  content: string;
  parent_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateChannelPayload {
  name: string;
  type?: ChannelType;
}

export interface CreateMessagePayload {
  content: string;
  parent_id?: string | null;
}
