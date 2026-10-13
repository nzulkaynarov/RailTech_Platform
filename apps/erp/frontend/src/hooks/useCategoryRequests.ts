import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { categoryRequestsApi, type CategoryRequestPayload } from '@/api/categoryRequestsApi';

/** Обращения своей компании — чтобы просьба не проваливалась в тишину (R6, D7). */
export const useMyCategoryRequests = () => useQuery({
  queryKey: ['category-requests'],
  queryFn: categoryRequestsApi.list,
  staleTime: 60_000,
});

export const useSubmitCategoryRequest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CategoryRequestPayload) => categoryRequestsApi.create(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['category-requests'] });
    },
  });
};
