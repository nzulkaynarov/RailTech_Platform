import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '@/api/adminApi';

export const useAdminQueue = (queueType?: string) =>
  useQuery({
    queryKey: ['admin-queue', queueType || 'all'],
    queryFn: () => adminApi.getQueue({ queue_type: queueType }),
    staleTime: 30_000,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });

export const useAdminPulse = (period: '7d' | '30d' | '90d' = '30d') =>
  useQuery({
    queryKey: ['admin-pulse', period],
    queryFn: () => adminApi.getPulse(period),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });

export const useAdminSearch = (q: string) =>
  useQuery({
    queryKey: ['admin-search', q],
    queryFn: () => adminApi.search(q),
    enabled: q.trim().length >= 2,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });

export const useAdminActivity = (entityType: string, entityId: number | string | undefined) =>
  useQuery({
    queryKey: ['admin-activity', entityType, entityId],
    queryFn: () => adminApi.getActivity(entityType, entityId as number),
    enabled: Boolean(entityType) && entityId !== undefined && entityId !== null && entityId !== '',
    staleTime: 15_000,
  });

export const useBulkVerifyKYC = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, level, reason }: { ids: number[]; level?: string; reason?: string }) =>
      adminApi.bulkVerifyKYC(ids, level, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['companies'] });
      queryClient.invalidateQueries({ queryKey: ['admin-queue'] });
      queryClient.invalidateQueries({ queryKey: ['platform-dashboard'] });
    },
  });
};

export const useBulkSubscriptionStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      ids,
      status,
      reason,
    }: {
      ids: number[];
      status: 'ACTIVE' | 'SUSPENDED';
      reason?: string;
    }) => adminApi.bulkSetSubscriptionStatus(ids, status, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
      queryClient.invalidateQueries({ queryKey: ['admin-queue'] });
      queryClient.invalidateQueries({ queryKey: ['platform-dashboard'] });
    },
  });
};
