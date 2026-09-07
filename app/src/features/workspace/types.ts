export type WorkspaceRole = 'owner' | 'admin' | 'member' | 'viewer';

export interface WorkspaceMember {
  id: string;
  backendMemberId?: string;
  name: string;
  email: string;
  role: WorkspaceRole;
  avatar?: string;
}

export interface WorkspaceInvite {
  id: string;
  email: string;
  role: WorkspaceRole;
  invitedAt: string;
}
