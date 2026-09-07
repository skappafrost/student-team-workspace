'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  getWorkspaceMembers as fetchMembers,
  getWorkspaceInvites as fetchInvites,
  setMemberRole as apiSetMemberRole,
  setInviteRole as apiSetInviteRole,
  inviteMember as apiInviteMember,
  removeInvite as apiRemoveInvite
} from '../service';
import { WorkspaceMember, WorkspaceRole, WorkspaceInvite } from '../types';

export function useWorkspaceMembers() {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [invites, setInvites] = useState<WorkspaceInvite[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const [m, i] = await Promise.all([fetchMembers(), fetchInvites()]);
      setMembers(m);
      setInvites(i);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const updateMemberRole = useCallback(async (memberId: string, role: WorkspaceRole) => {
    const updated = await apiSetMemberRole(memberId, role);
    setMembers(updated);
  }, []);

  const updateInviteRole = useCallback(async (inviteId: string, role: WorkspaceRole) => {
    const updated = await apiSetInviteRole(inviteId, role);
    setInvites(updated);
  }, []);

  const sendInvite = useCallback(async (email: string, role: WorkspaceRole) => {
    const invite = await apiInviteMember(email, role);
    setInvites((prev) => [...prev, invite]);
    return invite;
  }, []);

  const cancelInvite = useCallback(async (inviteId: string) => {
    const updated = await apiRemoveInvite(inviteId);
    setInvites(updated);
  }, []);

  return {
    members,
    invites,
    isLoading,
    refresh,
    updateMemberRole,
    updateInviteRole,
    sendInvite,
    cancelInvite
  };
}
