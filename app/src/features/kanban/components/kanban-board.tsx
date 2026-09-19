'use client';

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Kanban, KanbanBoard as KanbanBoardPrimitive, KanbanOverlay } from '@/components/ui/kanban';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { taskKeys, tasksQueryOptions } from '../api/queries';
import { createTask, deleteTask, updateTask } from '../api/service';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { Task, TaskStatus } from '../api/types';
import { TaskColumn } from './board-column';
import { TaskCard } from './task-card';
import { TaskDetailSheet } from './task-detail-sheet';
import { createRestrictToContainer } from '../utils/restrict-to-container';

const COLUMNS: TaskStatus[] = ['backlog', 'todo', 'doing', 'done'];

const COLUMN_LABELS: Record<TaskStatus, string> = {
  backlog: 'Backlog',
  todo: 'Todo',
  doing: 'Doing',
  done: 'Done'
};

function buildColumns(tasks: Task[] | undefined): Record<TaskStatus, Task[]> {
  const columns: Record<TaskStatus, Task[]> = {
    backlog: [],
    todo: [],
    doing: [],
    done: []
  };
  if (!tasks) return columns;
  for (const task of tasks) {
    const status = COLUMNS.includes(task.status) ? task.status : 'backlog';
    columns[status].push(task);
  }
  for (const key of COLUMNS) {
    columns[key] = columns[key].toSorted((a, b) => a.position - b.position);
  }
  return columns;
}

export function KanbanBoard({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { data: tasksData, isLoading } = useQuery(tasksQueryOptions(projectId));
  // Stable reference: `?? []` inline creates a new array every render, which
  // makes the columns-sync effect loop forever (setColumns -> render -> new
  // tasks ref -> setColumns...).
  const tasks = useMemo(() => tasksData ?? [], [tasksData]);

  const create = useMutation({
    mutationFn: (payload: { title: string; status: TaskStatus }) =>
      createTask(projectId, { title: payload.title, status: payload.status, priority: 'medium' }),
    onSuccess: () => {
      toast.success('Task created');
      return queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to create task');
    }
  });

  const update = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: { status: TaskStatus } }) =>
      updateTask(taskId, payload),
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to update task');
    }
  });

  const [columns, setColumns] = useState<Record<TaskStatus, Task[]>>(buildColumns(tasks));
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const containerRef = useRef<HTMLDivElement>(null);

  const toggleChecked = useCallback((taskId: string, selected: boolean) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(taskId);
      else next.delete(taskId);
      return next;
    });
  }, []);

  const bulkUpdate = useMutation({
    mutationFn: async (ids: string[]) => {
      await Promise.all(ids.map((id) => updateTask(id, { status: 'done' })));
    },
    onSuccess: () => {
      toast.success('Tasks marked done');
      setCheckedIds(new Set());
      return queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
    onError: () => toast.error('Bulk update failed')
  });

  const bulkDelete = useMutation({
    mutationFn: async (ids: string[]) => {
      await Promise.all(ids.map((id) => deleteTask(id)));
    },
    onSuccess: () => {
      toast.success('Tasks deleted');
      setCheckedIds(new Set());
      return queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
    onError: () => toast.error('Bulk delete failed')
  });

  // Keep local columns in sync with server data when switching projects or refetching.
  useEffect(() => {
    setColumns(buildColumns(tasks));
  }, [tasks]);

  const selectedTask = selectedTaskId
    ? (tasks.find((task) => task.id === selectedTaskId) ?? null)
    : null;

  // eslint-disable-next-line react-hooks/exhaustive-deps -- factory function, stable after mount
  const restrictToContainer = useCallback(
    createRestrictToContainer(() => containerRef.current),
    []
  );

  const handleDragEnd = (event: {
    active: { id: string | number };
    over?: { id: string | number } | null;
  }) => {
    const { active, over } = event;
    if (!over) return;

    const activeId = String(active.id);
    const overId = String(over.id);

    let sourceColumn: TaskStatus | null = null;
    for (const col of COLUMNS) {
      if (columns[col].some((task) => task.id === activeId)) {
        sourceColumn = col;
        break;
      }
    }
    if (!sourceColumn) return;

    let destinationColumn: TaskStatus | null = null;
    if (COLUMNS.includes(overId as TaskStatus)) {
      destinationColumn = overId as TaskStatus;
    } else {
      for (const col of COLUMNS) {
        if (columns[col].some((task) => task.id === overId)) {
          destinationColumn = col;
          break;
        }
      }
    }
    if (!destinationColumn || destinationColumn === sourceColumn) return;

    const task = columns[sourceColumn].find((t) => t.id === activeId);
    if (!task) return;

    setColumns((prev) => {
      const next = { ...prev };
      next[sourceColumn] = next[sourceColumn].filter((t) => t.id !== activeId);
      next[destinationColumn] = [
        ...next[destinationColumn],
        { ...task, status: destinationColumn }
      ];
      return next;
    });

    update.mutate(
      { taskId: activeId, payload: { status: destinationColumn } },
      {
        onError: () => {
          setColumns((prev) => {
            const next = { ...prev };
            next[destinationColumn] = next[destinationColumn].filter((t) => t.id !== activeId);
            next[sourceColumn] = [...next[sourceColumn], task];
            return next;
          });
        }
      }
    );
  };

  if (isLoading) {
    return <div className='text-muted-foreground text-sm'>Loading tasks...</div>;
  }

  return (
    <div ref={containerRef}>
      <Kanban
        value={columns}
        onValueChange={setColumns}
        getItemValue={(item) => item.id}
        modifiers={[restrictToContainer]}
        onDragEnd={handleDragEnd}
      >
        <div className='w-full overflow-x-auto rounded-md pb-4'>
          <KanbanBoardPrimitive className='flex flex-col items-start gap-4 md:flex-row'>
            {COLUMNS.map((columnValue) => (
              <TaskColumn
                key={columnValue}
                value={columnValue}
                label={COLUMN_LABELS[columnValue]}
                tasks={columns[columnValue]}
                onAdd={(title) =>
                  create.mutate({
                    title,
                    status: columnValue
                  })
                }
                onOpen={setSelectedTaskId}
                selectedIds={checkedIds}
                onToggleSelect={toggleChecked}
              />
            ))}
          </KanbanBoardPrimitive>
        </div>
        <KanbanOverlay>
          {({ value, variant }) => {
            if (variant === 'column') {
              const items = columns[(value as TaskStatus) ?? 'todo'] ?? [];
              return (
                <TaskColumn
                  value={(value as TaskStatus) ?? 'todo'}
                  label={COLUMN_LABELS[value as TaskStatus] ?? value}
                  tasks={items}
                  onAdd={() => {}}
                  onOpen={() => {}}
                />
              );
            }

            const task = tasks.find((t) => t.id === value);
            if (!task) return null;
            return <TaskCard task={task} />;
          }}
        </KanbanOverlay>
      </Kanban>

      <TaskDetailSheet
        task={selectedTask}
        onOpenChange={(open) => {
          if (!open) setSelectedTaskId(null);
        }}
      />

      {checkedIds.size > 0 && (
        <div
          role='toolbar'
          aria-label='Bulk task actions'
          className='bg-background/80 fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-full border px-4 py-2 shadow-lg backdrop-blur'
        >
          <span className='text-muted-foreground text-sm tabular-nums'>
            {checkedIds.size} selected
          </span>
          <Button
            size='sm'
            onClick={() => bulkUpdate.mutate([...checkedIds])}
            disabled={bulkUpdate.isPending || bulkDelete.isPending}
          >
            <Icons.check className='size-4' />
            Mark done
          </Button>
          <Button
            size='sm'
            variant='destructive'
            onClick={() => bulkDelete.mutate([...checkedIds])}
            disabled={bulkUpdate.isPending || bulkDelete.isPending}
          >
            <Icons.trash className='size-4' />
            Delete
          </Button>
          <Button size='sm' variant='ghost' onClick={() => setCheckedIds(new Set())}>
            Clear
          </Button>
        </div>
      )}
    </div>
  );
}
