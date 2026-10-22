import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "../shared/api/errors";

/** Повтор — один раз и не для ответов 4xx (401 `SESSION_EXPIRED`, 403, 404, 422 повтор не лечит). */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: true, staleTime: 5_000 },
    },
  });
}
