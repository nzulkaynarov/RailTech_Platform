import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/dashboardApi';

export const usePageStats = () => useQuery({
  queryKey: ['page-stats'],
  queryFn: dashboardApi.getPageStats,
  staleTime: 60_000,
  gcTime: 5 * 60_000,
});

export const usePlatformDashboard = () => useQuery({
  queryKey: ['platform-dashboard'],
  queryFn: dashboardApi.getPlatformDashboard,
  staleTime: 30_000,
  gcTime: 5 * 60_000,
  refetchInterval: 60_000,
});
