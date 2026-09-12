'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';

/**
 * Account self-service (S03): export data as JSON, delete account.
 * Deletion requires password confirmation and signs the user out.
 */
export default function AccountCard() {
  const [password, setPassword] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleExport = () => {
    // Plain navigation triggers the browser download via Content-Disposition.
    window.location.assign('/api/account');
  };

  const handleDelete = async () => {
    if (!password) {
      toast.error('Enter your password to confirm deletion.');
      return;
    }
    setBusy(true);
    try {
      const res = await fetch('/api/account', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
        credentials: 'include'
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        toast.error(data.error ?? 'Failed to delete account.');
        return;
      }
      toast.success('Account deleted.');
      window.location.assign('/auth/sign-in');
    } catch {
      toast.error('Network error while deleting account.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className='border-destructive/40'>
      <CardHeader>
        <CardTitle>Account</CardTitle>
        <CardDescription>Export your data or permanently delete your account.</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        <div>
          <Button variant='outline' onClick={handleExport}>
            Export my data (JSON)
          </Button>
        </div>

        {confirming ? (
          <div className='border-destructive/40 flex flex-col gap-3 rounded-md border p-4'>
            <p className='text-destructive text-sm font-medium'>
              This anonymizes your account and removes your memberships, files and sessions.
              Shared messages and tasks remain under &quot;Deleted user&quot;. This cannot be undone.
            </p>
            <div className='flex flex-col gap-2'>
              <Label htmlFor='delete-password'>Password</Label>
              <Input
                id='delete-password'
                type='password'
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete='current-password'
              />
            </div>
            <div className='flex gap-2'>
              <Button variant='destructive' disabled={busy} onClick={handleDelete}>
                {busy ? 'Deleting…' : 'Delete my account'}
              </Button>
              <Button
                variant='ghost'
                disabled={busy}
                onClick={() => {
                  setConfirming(false);
                  setPassword('');
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div>
            <Button variant='destructive' onClick={() => setConfirming(true)}>
              Delete account
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
