export type WorkspaceRole = 'owner' | 'co-owner' | 'admin' | 'member' | 'guest';

/**
 * Roles the API will accept on a role write. `owner` is absent on purpose:
 * ownership moves through transfer-ownership only. A caller that picks a role
 * at or above its own rank is refused by the server (403), which the settings
 * page surfaces as a toast — the roster screen has no current-user identity of
 * its own to filter the list further.
 */
export const ASSIGNABLE_WORKSPACE_ROLES: WorkspaceRole[] = ['co-owner', 'admin', 'member', 'guest'];

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
