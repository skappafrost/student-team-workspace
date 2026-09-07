import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query';
import { getFiles, uploadFile, deleteFile } from './service';

export const filesKeys = {
  all: ['files'] as const,
  list: () => [...filesKeys.all, 'list'] as const
};

export function filesQueryOptions() {
  return queryOptions({
    queryKey: filesKeys.list(),
    queryFn: getFiles,
    staleTime: 0
  });
}

export function useUploadFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: uploadFile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: filesKeys.list() });
    }
  });
}

export function useDeleteFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteFile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: filesKeys.list() });
    }
  });
}
