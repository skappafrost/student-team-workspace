'use client';

import { Badge } from '@/components/ui/badge';
import { KanbanItem } from '@/components/ui/kanban';
import type { Task } from '../api/types';

interface TaskCardProps extends Omit<React.ComponentProps<typeof KanbanItem>, 'value'> {
  task: Task;
  onOpen?: () => void;
}

export function TaskCard({ task, onOpen, ...props }: TaskCardProps) {
  return (
    <KanbanItem
      value={task.id}
      {...props}
      render={
        <div
          className='bg-card hover:bg-accent/40 cursor-pointer rounded-md border p-3 shadow-xs transition-colors'
          role='button'
          tabIndex={0}
          aria-label={`Open details for ${task.title}`}
          onClick={() => onOpen?.()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              onOpen?.();
            }
          }}
        />
      }
    >
      <div className='flex flex-col gap-2'>
        <div className='flex items-center justify-between gap-2'>
          <span className='line-clamp-1 text-sm font-medium'>{task.title}</span>
          <Badge
            variant={
              task.priority === 'high' || task.priority === 'urgent'
                ? 'destructive'
                : task.priority === 'medium'
                  ? 'warning'
                  : 'secondary'
            }
            className='pointer-events-none h-5 rounded-sm px-1.5 text-[11px] capitalize'
          >
            {task.priority}
          </Badge>
        </div>
        {task.description && (
          <p className='text-muted-foreground line-clamp-2 text-xs'>{task.description}</p>
        )}
      </div>
    </KanbanItem>
  );
}
