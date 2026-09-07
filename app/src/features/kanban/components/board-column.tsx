'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { KanbanColumn, KanbanColumnHandle } from '@/components/ui/kanban';
import type { Task, TaskStatus } from '../api/types';
import { QuickAddCard } from './quick-add-card';
import { TaskCard } from './task-card';

interface TaskColumnProps extends Omit<React.ComponentProps<typeof KanbanColumn>, 'children'> {
  value: TaskStatus;
  label: string;
  tasks: Task[];
  onAdd: (title: string) => void;
  onOpen: (taskId: string) => void;
}

export function TaskColumn({ value, label, tasks, onAdd, onOpen, ...props }: TaskColumnProps) {
  return (
    <KanbanColumn value={value} className='w-full shrink-0 md:w-[320px]' {...props}>
      <div className='flex items-center justify-between'>
        <div className='flex items-center gap-2'>
          <span className='text-sm font-semibold'>{label}</span>
          <Badge variant='secondary' className='pointer-events-none rounded-sm'>
            {tasks.length}
          </Badge>
        </div>
        <KanbanColumnHandle render={<Button variant='ghost' size='icon' />}>
          <Icons.gripVertical className='h-4 w-4' />
        </KanbanColumnHandle>
      </div>
      <div className='flex flex-col gap-2 p-0.5'>
        {tasks.map((task) => (
          <TaskCard key={task.id} task={task} onOpen={() => onOpen(task.id)} />
        ))}
      </div>
      <QuickAddCard onAdd={onAdd} />
    </KanbanColumn>
  );
}
