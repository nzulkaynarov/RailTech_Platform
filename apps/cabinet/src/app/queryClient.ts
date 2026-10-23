import { QueryCache, QueryClient } from '@tanstack/react-query';

import { isPortalApiError } from '@/api/portal';
import { ME_QUERY_KEY } from '@/session/session';

/**
 * React Query — единственное хранилище данных портала (CONVENTIONS.md §3). 401 на любом запросе, кроме
 * самой сессии, перезапрашивает `['me']`: в вебе это ведёт на страницу входа, в Mini App — к
 * повторному `POST /auth/telegram`.
 */
export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (isPortalApiError(error, 401) && query.queryKey[0] !== ME_QUERY_KEY[0]) {
          void client.invalidateQueries({ queryKey: ME_QUERY_KEY });
        }
      },
    }),
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => !isPortalApiError(error) && failureCount < 2,
        staleTime: 30 * 1000,
      },
      mutations: { retry: false },
    },
  });
  return client;
}
