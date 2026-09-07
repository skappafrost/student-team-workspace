'use client';

import { useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { useWorkspaceMembers } from '../hooks/use-workspace-members';
import { WorkspaceRole, WorkspaceMember, WorkspaceInvite } from '../types';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';

const ROLES: WorkspaceRole[] = ['owner', 'admin', 'member', 'viewer'];

function RoleSelect({
  value,
  onChange,
  disabled = false
}: {
  value: WorkspaceRole;
  onChange: (value: WorkspaceRole) => void | Promise<void>;
  disabled?: boolean;
}) {
  return (
    <Select
      value={value}
      onValueChange={(value) => onChange(value as WorkspaceRole)}
      disabled={disabled}
    >
      <SelectTrigger className='w-28 capitalize'>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {ROLES.map((role) => (
          <SelectItem key={role} value={role} className='capitalize'>
            {role}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function MemberRow({
  member,
  onRoleChange
}: {
  member: WorkspaceMember;
  onRoleChange: (id: string, role: WorkspaceRole) => void | Promise<void>;
}) {
  const initials = member.name
    .split(' ')
    .filter(Boolean)
    .map((n) => n[0])
    .join('')
    .toUpperCase();
  const isOwner = member.role === 'owner';

  return (
    <TableRow>
      <TableCell>
        <div className='flex items-center gap-3'>
          <Avatar>
            {member.avatar ? <AvatarImage src={member.avatar} alt={member.name} /> : null}
            <AvatarFallback>{initials || member.name.slice(0, 2).toUpperCase()}</AvatarFallback>
          </Avatar>
          <div>
            <div className='font-medium'>{member.name}</div>
            <div className='text-muted-foreground text-sm'>{member.email}</div>
          </div>
        </div>
      </TableCell>
      <TableCell>
        <RoleSelect
          value={member.role}
          onChange={(role) => onRoleChange(member.id, role)}
          disabled={isOwner}
        />
      </TableCell>
    </TableRow>
  );
}

function InviteRow({
  invite,
  onRoleChange,
  onCancel
}: {
  invite: WorkspaceInvite;
  onRoleChange: (id: string, role: WorkspaceRole) => void | Promise<void>;
  onCancel: (id: string) => void | Promise<void>;
}) {
  return (
    <TableRow data-invite-id={invite.id}>
      <TableCell>
        <div className='flex items-center gap-3'>
          <div className='bg-muted flex size-8 items-center justify-center rounded-full text-xs font-medium'>
            <Icons.mail className='size-4 text-muted-foreground' />
          </div>
          <div>
            <div className='font-medium'>{invite.email}</div>
            <div className='text-muted-foreground text-sm'>Pending invite</div>
          </div>
        </div>
      </TableCell>
      <TableCell>
        <div className='flex items-center gap-2'>
          <RoleSelect value={invite.role} onChange={(role) => onRoleChange(invite.id, role)} />
          <Button
            variant='ghost'
            size='icon'
            onClick={() => onCancel(invite.id)}
            aria-label='Cancel invite'
          >
            <Icons.trash className='size-4 text-muted-foreground' />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

export default function WorkspaceSettingsPage() {
  const {
    members,
    invites,
    isLoading,
    updateMemberRole,
    updateInviteRole,
    sendInvite,
    cancelInvite
  } = useWorkspaceMembers();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<WorkspaceRole>('member');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) {
      toast.error('Please enter an email address.');
      return;
    }
    setIsSubmitting(true);
    try {
      await sendInvite(email.trim(), role);
      toast.success(`Invitation sent to ${email.trim()}`);
      setEmail('');
      setRole('member');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to send invitation.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMemberRoleChange = async (id: string, role: WorkspaceRole) => {
    try {
      await updateMemberRole(id, role);
      toast.success('Role updated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update role.');
    }
  };

  const handleInviteRoleChange = async (id: string, role: WorkspaceRole) => {
    try {
      await updateInviteRole(id, role);
      toast.success('Invite role updated');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update invite role.');
    }
  };

  const handleCancelInvite = async (id: string) => {
    try {
      await cancelInvite(id);
      toast.success('Invite cancelled');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to cancel invite.');
    }
  };

  return (
    <PageContainer
      pageTitle='Workspace settings'
      pageDescription='Manage members, invites, and roles.'
    >
      <div className='grid gap-6'>
        <Card>
          <CardHeader>
            <CardTitle>Invite member</CardTitle>
            <CardDescription>Send an invitation to join this workspace.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleInvite} className='flex items-end gap-3'>
              <div className='flex-1 space-y-2'>
                <Label htmlFor='invite-email'>Email address</Label>
                <Input
                  id='invite-email'
                  type='email'
                  placeholder='colleague@example.com'
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className='w-40 space-y-2'>
                <Label htmlFor='invite-role'>Role</Label>
                <Select value={role} onValueChange={(value) => setRole(value as WorkspaceRole)}>
                  <SelectTrigger id='invite-role' className='w-full capitalize'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r} className='capitalize'>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button type='submit' className='gap-2' disabled={isSubmitting}>
                <Icons.add className='size-4' />
                Invite
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Members</CardTitle>
            <CardDescription>People with access to this workspace.</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className='text-muted-foreground py-8 text-center'>Loading members…</div>
            ) : members.length === 0 ? (
              <div className='text-muted-foreground py-8 text-center'>No members yet.</div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead className='w-40'>Role</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map((member) => (
                    <MemberRow
                      key={member.id}
                      member={member}
                      onRoleChange={handleMemberRoleChange}
                    />
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {invites.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Pending invites</CardTitle>
              <CardDescription>Invitations that have not been accepted yet.</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead className='w-48'>Role</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invites.map((invite) => (
                    <InviteRow
                      key={invite.id}
                      invite={invite}
                      onRoleChange={handleInviteRoleChange}
                      onCancel={handleCancelInvite}
                    />
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </div>
    </PageContainer>
  );
}
