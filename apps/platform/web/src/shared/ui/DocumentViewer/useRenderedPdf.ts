import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/errors";

/**
 * «Построить → дождаться → показать» для документов, которые сервер строит в фоне (образец бланка, образец шаблона
 * письма, письмо на бланке): когда сервер сообщил «готов» (`ready`), байты скачиваются один раз; пока строится новая
 * версия, `data` остаётся прежней — на экране нет мигания. Сам запрос на построение и опрос состояния остаются у
 * вызывающего (у каждого документа свои ручки BFF); общее здесь — скачивание и удержание прежнего файла.
 *
 * `refreshKey` — признак версии (дата запроса, «окончательный»): сменился, когда документ снова готов, — файл
 * скачивается заново.
 */
export function useRenderedPdf({
  id,
  ready,
  queryKey,
  url,
  refreshKey,
  gcTime,
}: {
  id: string | null;
  ready: boolean;
  queryKey: QueryKey;
  url: string;
  refreshKey?: string;
  gcTime?: number;
}) {
  const client = useQueryClient();
  const seen = useRef(refreshKey);
  const keyText = JSON.stringify(queryKey);
  useEffect(() => {
    if (ready && seen.current !== refreshKey) {
      seen.current = refreshKey;
      void client.invalidateQueries({ queryKey: JSON.parse(keyText) as QueryKey });
    }
  }, [client, keyText, ready, refreshKey]);
  const query = useQuery({
    enabled: Boolean(id) && ready,
    queryKey,
    staleTime: Infinity,
    ...(gcTime === undefined ? {} : { gcTime }),
    queryFn: async (): Promise<ArrayBuffer> => {
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) {
        throw new ApiError(response.status, "HTTP_ERROR", `HTTP ${String(response.status)}`);
      }
      return response.arrayBuffer();
    },
  });
  // Пока готовится новый вариант, на экране прежний.
  const [shown, setShown] = useState<ArrayBuffer | null>(null);
  if (query.data && query.data !== shown) setShown(query.data);
  return {
    data: query.data ?? shown,
    isFetching: query.isFetching,
    isError: query.isError,
    refetch: query.refetch,
  };
}
