/**
 * Опрос вместо потока событий в фазах P1–P3 (docs/architecture/platform-bff.md §5, docs/architecture/platform-frontend.md §7): «Моя очередь», бейджи меню и
 * колокольчик обновляются раз в 30 секунд и при возврате на вкладку (TanStack Query: `refetchOnWindowFocus` берёт
 * только устаревшие данные, `staleTime` клиента — 5 с). Фоновые вкладки не опрашиваются.
 */
export const POLL_INTERVAL_MS = 30_000;

export const pollQuery = {
  refetchInterval: POLL_INTERVAL_MS,
  refetchOnWindowFocus: true,
  refetchIntervalInBackground: false,
} as const;
