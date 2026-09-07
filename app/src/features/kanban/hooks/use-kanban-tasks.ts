'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { toast } from 'sonner';
import { taskKeys, tasksQueryOptions } from '../api/queries';
import { createTask, deleteTask, updateTask } from '../api/service';
import { TaskStatus, UpdateTaskPayload } from '../api/types';

export function useCreateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: { projectId: string; title: string; status?: TaskStatus }) =>
      createTask(payload.projectId, {
        title: payload.title,
        status: payload.status ?? 'todo',
        priority: 'medium'
      }),
    onSuccess: () => {
      toast.success('Task created');
      return queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to create task');
    }
  });
}

export function useUpdateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: UpdateTaskPayload }) =>
      updateTask(taskId, payload),
    onSuccess: () => {
      toast.success('Task updated');
      return queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to update task');
    }
  });
}

export function useDeleteTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (taskId: string) => deleteTask(taskId),
    onSuccess: () => {
      toast.success('Task deleted');
      return queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to delete task');
    }
  });
}

export function useTasks(projectId: string) {
  const queryClient = useQueryClient();
  const query = useQuery(tasksQueryOptions(projectId));
  const create = useCreateTask();
  const update = useUpdateTask();
  const remove = useDeleteTask();

  const invalidate = useCallback(() => {
    return queryClient.invalidateQueries({ queryKey: taskKeys.all });
  }, [queryClient]);

  return {
    tasks: query.data ?? [],
    isLoading: query.isLoading,
    isPending: query.isPending,
    error: query.error,
    create,
    update,
    remove,
    invalidate
  };
}
