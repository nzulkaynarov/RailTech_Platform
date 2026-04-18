import { useQuery } from '@tanstack/react-query';
import { statusChoicesApi, Phase2StatusChoices } from '@/api/statusChoicesApi';

/**
 * Single query for all Phase 2 status choices.
 * Lookups change rarely — cached 30 min, no auto-refetch.
 */
export const usePhase2StatusChoices = () => useQuery<Phase2StatusChoices>({
  queryKey: ['phase2-status-choices'],
  queryFn: statusChoicesApi.getAll,
  staleTime: 30 * 60_000,
  gcTime: 60 * 60_000,
});
