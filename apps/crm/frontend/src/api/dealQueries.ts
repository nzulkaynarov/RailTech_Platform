/** Запросы «Сделки» (Q-013, ADR-0019). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createDeal, dealOptions, dealsSummary, listDeals, updateDeal } from "./generated/crm";
import type { DealCreate, DealUpdate, ListDealsParams } from "./generated/model";
import { compact, unwrap } from "./http";

export const dealKeys = {
  all: ["deals"] as const,
  list: (params: ListDealsParams) => ["deals", "list", params] as const,
  summary: (days: number) => ["deals", "summary", days] as const,
};

export const useDeals = (params: ListDealsParams) =>
  useQuery({
    queryKey: dealKeys.list(params),
    queryFn: async () => unwrap(await listDeals(compact(params))),
  });

export const useDealsSummary = (days: number, enabled = true) =>
  useQuery({
    queryKey: dealKeys.summary(days),
    queryFn: async () => unwrap(await dealsSummary({ days })),
    enabled,
  });

export const useDealOptions = () =>
  useQuery({
    queryKey: ["deals", "options"],
    queryFn: async () => unwrap(await dealOptions()),
    staleTime: 60_000,
  });

export type DealSave = { id: number | null; body: DealCreate | DealUpdate };

export function useSaveDeal() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, body }: DealSave) =>
      id === null
        ? unwrap(await createDeal(body as DealCreate))
        : unwrap(await updateDeal(id, body as DealUpdate)),
    onSettled: () => client.invalidateQueries({ queryKey: dealKeys.all }),
  });
}
