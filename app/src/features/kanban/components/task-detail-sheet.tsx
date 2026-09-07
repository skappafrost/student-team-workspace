'use client';

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { useWorkspaceMembers } from '@/features/workspace/hooks/use-workspace-members';
import { Task, TaskPriority, TaskStatus } from '../api/types';
import { useUpdateTask } from '../hooks/use-kanban-tasks';
import { AISummaryCard } from '@/features/ai/components/ai-summary-card';

const PRIORITY_LABEL: Record<TaskPriority, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  urgent: 'Urgent'
};

const STATUS_LABEL: Record<TaskStatus, string> = {
  backlog: 'Backlog',
  todo: 'Todo',
  doing: 'Doing',
  done: 'Done'
};

const PRIORITY_ORDER: TaskPriority[] = ['low', 'medium', 'high', 'urgent'];
const STATUS_ORDER: TaskStatus[] = ['backlog', 'todo', 'doing', 'done'];

interface TaskDetailSheetProps {
  task: Task | null;
  onOpenChange: (open: boolean) => void;
}

export function TaskDetailSheet({ task, onOpenChange }: TaskDetailSheetProps) {
  return (
    <Sheet open={!!task} onOpenChange={onOpenChange}>
      <SheetContent className='gap-0 p-0 sm:max-w-md' aria-describedby={undefined}>
        {task && <TaskDetailBody key={task.id} task={task} />}
      </SheetContent>
    </Sheet>
  );
}

function TaskDetailBody({ task }: { task: Task }) {
  const update = useUpdateTask();
  const { members } = useWorkspaceMembers();

  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description ?? '');
  const [priority, setPriority] = useState<TaskPriority>(task.priority);
  const [status, setStatus] = useState<TaskStatus>(task.status);
  const [assigneeId, setAssigneeId] = useState<string | null>(task.assignee_id);
  const [position, setPosition] = useState<string>(String(task.position));

  useEffect(() => {
    setTitle(task.title);
    setDescription(task.description ?? '');
    setPriority(task.priority);
    setStatus(task.status);
    setAssigneeId(task.assignee_id);
    setPosition(String(task.position));
  }, [task.id]);

  const handleSave = () => {
    const payload: {
      title?: string;
      description?: string | null;
      priority?: TaskPriority;
      status?: TaskStatus;
      assignee_id?: string | null;
      position?: number;
    } = {};

    if (title !== task.title) payload.title = title;
    if (description !== (task.description ?? '')) payload.description = description || null;
    if (priority !== task.priority) payload.priority = priority;
    if (status !== task.status) payload.status = status;
    if (assigneeId !== task.assignee_id) payload.assignee_id = assigneeId;

    const positionNum = Number(position);
    if (!Number.isNaN(positionNum) && positionNum !== task.position) {
      payload.position = positionNum;
    }

    if (Object.keys(payload).length > 0) {
      update.mutate({ taskId: task.id, payload });
    }
  };

  const priorityVariant =
    priority === 'urgent' || priority === 'high'
      ? 'destructive'
      : priority === 'medium'
        ? 'warning'
        : 'secondary';

  return (
    <>
      <SheetHeader>
        <SheetTitle className='line-clamp-2 pr-8'>{title}</SheetTitle>
        <SheetDescription render={<div className='flex items-center gap-2 pt-1' />}>
          <Badge variant={priorityVariant} className='rounded-sm text-[11px] capitalize'>
            {PRIORITY_LABEL[priority]}
          </Badge>
          <Badge variant='outline' className='rounded-sm text-[11px] capitalize'>
            {STATUS_LABEL[status]}
          </Badge>
        </SheetDescription>
      </SheetHeader>

      <div className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4'>
        <Separator />

        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='task-title'>Title</Label>
          <Input
            id='task-title'
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
            onBlur={handleSave}
          />
        </div>

        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='task-description'>Description</Label>
          <Textarea
            id='task-description'
            placeholder='Add a more detailed description...'
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            onBlur={handleSave}
            className='min-h-28'
          />
        </div>

        <div className='grid grid-cols-2 gap-3'>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='task-priority'>Priority</Label>
            <Select
              value={priority}
              onValueChange={(value) => {
                const next = value as TaskPriority;
                setPriority(next);
                update.mutate({ taskId: task.id, payload: { priority: next } });
              }}
            >
              <SelectTrigger id='task-priority'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRIORITY_ORDER.map((p) => (
                  <SelectItem key={p} value={p}>
                    {PRIORITY_LABEL[p]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='task-status'>Status</Label>
            <Select
              value={status}
              onValueChange={(value) => {
                const next = value as TaskStatus;
                setStatus(next);
                update.mutate({ taskId: task.id, payload: { status: next } });
              }}
            >
              <SelectTrigger id='task-status'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_ORDER.map((s) => (
                  <SelectItem key={s} value={s}>
                    {STATUS_LABEL[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className='grid grid-cols-2 gap-3'>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='task-assignee'>Assignee</Label>
            <Select
              value={assigneeId ?? 'none'}
              onValueChange={(value) => {
                const next = value === 'none' ? null : value;
                setAssigneeId(next);
                update.mutate({ taskId: task.id, payload: { assignee_id: next } });
              }}
            >
              <SelectTrigger id='task-assignee'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='none'>Unassigned</SelectItem>
                {members.map((member) => (
                  <SelectItem key={member.id} value={member.id}>
                    {member.name || member.email}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='task-position'>Position</Label>
            <Input
              id='task-position'
              type='number'
              value={position}
              onChange={(e) => setPosition(e.currentTarget.value)}
              onBlur={handleSave}
            />
          </div>
        </div>

        <Button className='mt-2 w-full' disabled={update.isPending} onClick={handleSave} size='sm'>
          {update.isPending ? 'Saving...' : 'Save changes'}
        </Button>

        <AISummaryCard kind='task' refId={task.id} title='Summarize task' />
      </div>
    </>
  );
}
