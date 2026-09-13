import { WorkspaceMember, WorkspaceRole, WorkspaceInvite } from './types';
import { createApiClient } from '@/lib/api-client';

const apiRequest = createApiClient('/api/workspace');


function mapBackendMember(member: {
  id: string;
  user_id?: string;
  name?: string;
  email?: string;
  role: string;
  joined_at?: string;
  user?: { display_name?: string; email?: string; avatar_url?: string };
}): WorkspaceMember {
  return {
    // Prefer backend user_id (role-update API addresses members by user_id);
    // fall back to row id so fixture/seeds without user_id still get unique keys.
    id: member.user_id ?? member.id,
    name: member.user?.display_name || member.name || member.user_id || 'Unknown',
    email: member.user?.email || member.email || '',
    role: member.role as WorkspaceRole,
    avatar: member.user?.avatar_url
  };
}

function mapBackendInvite(invite: {
  id: string;
  email: string;
  role: string;
  created_at?: string;
  expires_at?: string;
}): WorkspaceInvite {
  return {
    id: invite.id,
    email: invite.email,
    role: invite.role as WorkspaceRole,
    invitedAt: invite.created_at || new Date().toISOString()
  };
}

export async function getWorkspaceMembers(): Promise<WorkspaceMember[]> {
  const data = await apiRequest<{ members: Array<Record<string, unknown>> }>('/members');
  const members = data.members || [];
  return members.map((m) => mapBackendMember(m as Parameters<typeof mapBackendMember>[0]));
}

export async function getWorkspaceInvites(): Promise<WorkspaceInvite[]> {
  const data = await apiRequest<{ invites: Array<Record<string, unknown>> }>('/invites');
  const invites = data.invites || [];
  return invites.map((i) => mapBackendInvite(i as Parameters<typeof mapBackendInvite>[0]));
}

export async function setMemberRole(
  memberId: string,
  role: WorkspaceRole
): Promise<WorkspaceMember[]> {
  const data = await apiRequest<{ members: Array<Record<string, unknown>> }>('/members', {
    method: 'PATCH',
    body: JSON.stringify({ memberId, role })
  });
  return (data.members || []).map((m) =>
    mapBackendMember(m as Parameters<typeof mapBackendMember>[0])
  );
}

export async function setInviteRole(
  inviteId: string,
  role: WorkspaceRole
): Promise<WorkspaceInvite[]> {
  const data = await apiRequest<{ invites: Array<Record<string, unknown>> }>('/invites', {
    method: 'PATCH',
    body: JSON.stringify({ inviteId, role })
  });
  return (data.invites || []).map((i) =>
    mapBackendInvite(i as Parameters<typeof mapBackendInvite>[0])
  );
}

export async function inviteMember(email: string, role: WorkspaceRole): Promise<WorkspaceInvite> {
  const data = await apiRequest<{ invite: Record<string, unknown> }>('/invites', {
    method: 'POST',
    body: JSON.stringify({ email, role })
  });
  return mapBackendInvite(data.invite as Parameters<typeof mapBackendInvite>[0]);
}

export async function removeInvite(inviteId: string): Promise<WorkspaceInvite[]> {
  const data = await apiRequest<{ invites: Array<Record<string, unknown>> }>(
    `/invites?inviteId=${encodeURIComponent(inviteId)}`,
    { method: 'DELETE' }
  );
  return (data.invites || []).map((i) =>
    mapBackendInvite(i as Parameters<typeof mapBackendInvite>[0])
  );
}
