'use client';

import * as React from 'react';

import PageContainer from '@/components/layout/page-container';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { createApiClient } from '@/lib/api-client';

const apiRequest = createApiClient('/api/workspace/audit-log');

interface AuditEntry {
  id: string;
  actor_id: string;
  actor_name: string;
  verb: string;
  target_type: string;
  target_id: string;
  target_label: string | null;
  created_at: string;
}

const TARGET_TYPES = ['task', 'page', 'file', 'message', 'event', 'project', 'channel'];

export default function AuditLogPage() {
  const [entries, setEntries] = React.useState<AuditEntry[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [q, setQ] = React.useState('');
  const [targetType, setTargetType] = React.useState<string>('all');

  const load = React.useCallback(async (query: string, type: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (query.trim()) params.set('q', query.trim());
      if (type !== 'all') params.set('target_type', type);
      const suffix = params.size > 0 ? `?${params.toString()}` : '';
      const data = await apiRequest<{ entries: AuditEntry[] }>(suffix);
      setEntries(data.entries || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit log');
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load(q, targetType);
  }, [load, targetType]);

  return (
    <PageContainer
      pageTitle='Audit Log'
      pageDescription='Full workspace activity history. Admin only.'
    >
      <div className='flex flex-col gap-4'>
        <div className='flex items-center gap-2'>
          <Input
            placeholder='Search by label…'
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void load(q, targetType);
            }}
            className='max-w-xs'
            aria-label='Search audit log'
          />
          <Select
            value={targetType}
            onValueChange={(value) => setTargetType(value ?? 'all')}
          >
            <SelectTrigger className='w-40' aria-label='Filter by target type'>
              <SelectValue placeholder='All types' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='all'>All types</SelectItem>
              {TARGET_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {error ? (
          <p className='text-destructive text-sm' role='alert'>
            {error} — admin role required.
          </p>
        ) : null}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Target</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5}>Loading…</TableCell>
              </TableRow>
            ) : entries.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className='text-muted-foreground'>
                  No audit entries found.
                </TableCell>
              </TableRow>
            ) : (
              entries.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className='whitespace-nowrap'>
                    {new Date(entry.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>{entry.actor_name}</TableCell>
                  <TableCell>{entry.verb}</TableCell>
                  <TableCell>
                    <Badge variant='secondary'>{entry.target_type}</Badge>
                  </TableCell>
                  <TableCell className='max-w-64 truncate'>
                    {entry.target_label || entry.target_id}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </PageContainer>
  );
}
