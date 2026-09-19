'use client';

import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { KanbanItem } from '@/components/ui/kanban';
import { cn } from '@/lib/utils';
import type { Task } from '../api/types';

interface TaskCardProps extends Omit<React.ComponentProps<typeof KanbanItem>, 'value'> {
  task: Task;
  onOpen?: () => void;
  selected?: boolean;
  onToggleSelect?: (selected: boolean) => void;
}

export function TaskCard({ task, onOpen, selected, onToggleSelect, ...props }: TaskCardProps) {
  return (
    <KanbanItem
      value={task.id}
      {...props}
      render={
        <div
          className={cn(
            'group/card bg-card hover:bg-accent/40 relative cursor-pointer rounded-md border p-3 shadow-xs transition-colors',
            selected && 'ring-primary ring-2'
          )}
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
      {onToggleSelect && (
        <Checkbox
          aria-label={`Select ${task.title}`}
          checked={selected ?? false}
          onCheckedChange={(checked) => onToggleSelect(checked === true)}
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          className={cn(
            'absolute top-2 left-2 z-10 bg-background transition-opacity',
            selected ? 'opacity-100' : 'opacity-0 group-hover/card:opacity-100'
          )}
        />
      )}
      <div className='flex flex-col gap-2'>
        <div className='flex items-center justify-between gap-2'>
          <span
            className={cn(
              'line-clamp-1 text-sm font-medium',
              onToggleSelect && (selected ? 'pl-6' : 'group-hover/card:pl-6')
            )}
          >
            {task.title}
          </span>
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
