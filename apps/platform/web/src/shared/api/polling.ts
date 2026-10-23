import { useMemo } from "react";

import { useStreamLive } from "./streamState";

/**
 * Опрос — запасной путь (docs/architecture/platform-bff.md §5, docs/architecture/platform-frontend.md §7). Пока поток подсказок BFF (`/events/stream`, SSE) жив,
 * «Моя очередь», бейджи меню и колокольчик обновляются по событию шины, а опрос редкий — страховка от потерянной
 * подсказки. Поток оборвался — прежний опрос раз в 30 секунд и при возврате на вкладку (TanStack Query:
 * `refetchOnWindowFocus` берёт только устаревшие данные, `staleTime` клиента — 5 с). Фоновые вкладки не опрашиваются.
 */
export const POLL_INTERVAL_MS = 30_000;
/** Опрос при живом потоке: подсказки приходят сами, это только страховка. */
export const STREAM_POLL_INTERVAL_MS = 300_000;

export function pollInterval(streamLive: boolean): number {
  return streamLive ? STREAM_POLL_INTERVAL_MS : POLL_INTERVAL_MS;
}

/** Параметры запроса «живых» данных: интервал зависит от того, жив ли поток подсказок. */
export function usePollQuery() {
  const live = useStreamLive();
  return useMemo(
    () =>
      ({
        refetchInterval: pollInterval(live),
        refetchOnWindowFocus: true,
        refetchIntervalInBackground: false,
      }) as const,
    [live],
  );
}
