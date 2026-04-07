import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/dashboardApi';

export const usePageStats = () => useQuery({
  queryKey: ['page-stats'],
  queryFn: dashboardApi.getPageStats,
  staleTime: 60_000,    // кеш 1 минуту
  gcTime: 5 * 60_000,   // в памяти 5 минут
});
