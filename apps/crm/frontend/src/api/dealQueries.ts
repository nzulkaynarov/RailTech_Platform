/** Запросы «Сделки» (Q-013, ADR-0019). */
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  createDeal,
  getDealsSummaryQueryKey,
  getListDealsQueryKey,
  updateDeal,
  useDealOptions as useDealOptionsQuery,
  useDealsSummary as useDealsSummaryQuery,
  useListDeals,
} from "./generated/crm";
import type { DealCreate, DealUpdate, ListDealsParams } from "./generated/model";
import { compact } from "./http";

/** Таблица не пустеет при смене страницы/фильтра: показываем прошлую страницу до ответа. */
export const useDeals = (params: ListDealsParams) =>
  useListDeals(compact(params), { query: { placeholderData: keepPreviousData } });

export const useDealsSummary = (days: number, enabled = true) =>
  useDealsSummaryQuery({ days }, { query: { enabled } });

export const useDealOptions = () => useDealOptionsQuery({ query: { staleTime: 60_000 } });

export type DealSave = { id: number | null; body: DealCreate | DealUpdate };

export function useSaveDeal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: DealSave) =>
      id === null ? await createDeal(body as DealCreate) : await updateDeal(id, body as DealUpdate),
    onSettled: () =>
      Promise.all(
        [getListDealsQueryKey(), getDealsSummaryQueryKey()].map((queryKey) =>
          client.invalidateQueries({ queryKey }),
        ),
      ),
  });
}
