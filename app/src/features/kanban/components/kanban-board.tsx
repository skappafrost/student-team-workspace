'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { Kanban, KanbanBoard as KanbanBoardPrimitive, KanbanOverlay } from '@/components/ui/kanban';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { taskKeys, tasksQueryOptions } from '../api/queries';
import { createTask, updateTask } from '../api/service';
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
  const { data: tasks = [], isLoading } = useQuery(tasksQueryOptions(projectId));

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
  const containerRef = useRef<HTMLDivElement>(null);

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
    </div>
  );
}
