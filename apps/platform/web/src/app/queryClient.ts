import { type DefaultOptions, type Query, QueryClient, type QueryKey } from "@tanstack/react-query";

import { ApiError } from "../shared/api/errors";

/** Повтор — один раз и не для ответов 4xx (401 `SESSION_EXPIRED`, 403, 404, 422 повтор не лечит). */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

/**
 * Данные на месте при смене фильтра, вкладки и страницы (UX-1c, аудит 2026-10-30, S8): пока грузится ответ с новыми
 * параметрами того же адреса (`/api/v1/crm/leads` с другим `scope`), список показывает прежние строки
 * (`isPlaceholderData`), а не скелетон. Карточка другого объекта — другой адрес (`/crm/leads/L-2`): там прежние данные
 * не подставляются, чтобы не показать чужую карточку под новым номером.
 */
export function keepSamePathData(queryKey: QueryKey) {
  return (previous: unknown, previousQuery: Query | undefined): unknown =>
    previousQuery !== undefined && previousQuery.queryKey[0] === queryKey[0] ? previous : undefined;
}

/**
 * Клиент запросов Платформы: умолчания запросов и `keepSamePathData` для каждого запроса, где экран не задал своё.
 * Подстановка — через `defaultQueryOptions`: только там известен ключ запроса.
 */
export function createQueryClient(
  queries: NonNullable<DefaultOptions["queries"]> = {},
): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: true, staleTime: 5_000, ...queries },
    },
  });
  const defaults = client.defaultQueryOptions.bind(client) as (options: unknown) => {
    placeholderData?: unknown;
    queryKey: QueryKey;
  };
  const withPlaceholder = (options: unknown) => {
    const defaulted = defaults(options);
    if (defaulted.placeholderData === undefined) {
      defaulted.placeholderData = keepSamePathData(defaulted.queryKey);
    }
    return defaulted;
  };
  client.defaultQueryOptions = withPlaceholder as unknown as QueryClient["defaultQueryOptions"];
  return client;
}
