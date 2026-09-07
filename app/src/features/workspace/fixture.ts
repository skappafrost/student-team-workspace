import { WorkspaceMember, WorkspaceInvite, WorkspaceRole } from './types';

export const seededMembers: WorkspaceMember[] = [
  {
    id: 'usr_1',
    name: 'Alice Nguyen',
    email: 'alice@example.com',
    role: 'owner',
    avatar: undefined
  },
  {
    id: 'usr_2',
    name: 'Bob Tran',
    email: 'bob@example.com',
    role: 'admin',
    avatar: undefined
  },
  {
    id: 'usr_3',
    name: 'Carol Le',
    email: 'carol@example.com',
    role: 'member',
    avatar: undefined
  },
  {
    id: 'usr_4',
    name: 'David Pham',
    email: 'david@example.com',
    role: 'viewer',
    avatar: undefined
  }
];

export const seededInvites: WorkspaceInvite[] = [
  {
    id: 'inv_1',
    email: 'pending.member@example.com',
    role: 'member' as WorkspaceRole,
    invitedAt: new Date().toISOString()
  }
];
