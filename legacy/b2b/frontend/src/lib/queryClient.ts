import { QueryClient, MutationCache } from '@tanstack/react-query';
import { toast } from 'sonner';

import { translateApiError } from './apiError';

/**
 * The single app-wide React Query client.
 *
 * Exported as a module singleton (not created inline in main.tsx) so auth flows
 * can wipe it on identity change: on a SHARED browser, logging out then logging
 * in as a different user MUST NOT serve the previous user's cached rows. With
 * refetchOnMount:false + staleTime 2m + gcTime 10m, a fresh mount would otherwise
 * read the prior tenant's ['deals']/['quotes']/analytics cache with no network
 * request — a cross-tenant leak. authStore.login/logout call `queryClient.clear()`.
 */
export const queryClient = new QueryClient({
  // Single source of truth for mutation errors: any mutation that does not opt out
  // surfaces a localised toast. Prevents the "action silently failed" class of bugs.
  // A mutation can opt out with meta: { skipErrorToast: true } when it shows its own UI.
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (mutation.meta?.skipErrorToast) return;
      toast.error(translateApiError(error));
    },
  }),
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // Don't retry 4xx client errors (auth, not-found, etc) — they won't succeed
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 1;
      },
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchOnMount: false,
      staleTime: 2 * 60_000,
      gcTime: 10 * 60_000,
    },
  },
});
