'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { toast } from 'sonner';
import { projectKeys, projectsQueryOptions } from '../queries';
import { createProject, deleteProject, updateProject } from '../service';
import { CreateProjectPayload, UpdateProjectPayload } from '../types';

export function useProjects() {
  const queryClient = useQueryClient();
  const query = useQuery(projectsQueryOptions());

  const invalidate = useCallback(() => {
    return queryClient.invalidateQueries({ queryKey: projectKeys.all });
  }, [queryClient]);

  const create = useMutation({
    mutationFn: (payload: CreateProjectPayload) => createProject(payload),
    onSuccess: () => {
      toast.success('Project created');
      return invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to create project');
    }
  });

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateProjectPayload }) =>
      updateProject(id, payload),
    onSuccess: () => {
      toast.success('Project updated');
      return invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to update project');
    }
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: () => {
      toast.success('Project deleted');
      return invalidate();
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : 'Failed to delete project');
    }
  });

  return {
    projects: query.data ?? [],
    isLoading: query.isLoading,
    isPending: query.isPending,
    error: query.error,
    create,
    update,
    remove,
    invalidate
  };
}
