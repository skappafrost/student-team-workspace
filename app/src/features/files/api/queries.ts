import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query';
import { getFiles, uploadFile, updateFile, deleteFile } from './service';
import type { FileLinkFilter } from './service';

export const filesKeys = {
  all: ['files'] as const,
  list: () => [...filesKeys.all, 'list'] as const,
  linked: (filter: FileLinkFilter) => [...filesKeys.all, 'linked', filter] as const
};

export function filesQueryOptions() {
  return queryOptions({
    queryKey: filesKeys.list(),
    queryFn: () => getFiles(),
    staleTime: 0
  });
}

export function linkedFilesQueryOptions(filter: FileLinkFilter) {
  return queryOptions({
    queryKey: filesKeys.linked(filter),
    queryFn: () => getFiles(filter),
    staleTime: 0
  });
}

export function useUploadFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: uploadFile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: filesKeys.all });
    }
  });
}

export function useUpdateFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof updateFile>[1] }) =>
      updateFile(id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: filesKeys.all });
    }
  });
}

export function useDeleteFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteFile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: filesKeys.all });
    }
  });
}
