/**
 * Сделки и заявки: список/карточка, создание и правка, маршрутизация продавцам (R1/R3),
 * взятие в работу и освобождение, этапы воронки и статусы КП.
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi, QuoteItem } from '../../api/crmApi';

export const useDeals = () => useQuery({
  queryKey: ['deals'],
  queryFn: crmApi.getDeals,
});

export const useDeal = (id: number) => useQuery({
  queryKey: ['deals', id],
  queryFn: () => crmApi.getDeal(id),
  enabled: !!id,
});

export interface QuoteItemsFilterParams {
  deal_id?: number;
  product_is_null?: boolean;
}

export const useQuoteItems = (params?: QuoteItemsFilterParams) => useQuery({
  queryKey: ['quote-items', params],
  queryFn: () => crmApi.getQuoteItems(params),
});

export const useUpdateQuoteItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<QuoteItem> }) => crmApi.updateQuoteItem(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quote-items'] });
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

// Transactional bulk save of the edited КП lines (P0-4). ONE request, ONE recalc, ONE set
// of invalidations — replaces the old per-row `for … await updateQuoteItem` loop. The caller
// handles the QUOTE_ITEMS_BULK_INVALID per-row errors (nothing is written on rejection).
export const useBulkUpdateQuoteItems = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ quoteId, items }: { quoteId: number; items: Array<Partial<QuoteItem> & { id: number }> }) =>
      crmApi.bulkUpdateQuoteItems(quoteId, items),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quote-items'] });
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

export const useCreateDeal = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { title?: string; notes?: string; contact_id?: number; without_client?: boolean }) =>
      crmApi.createDeal(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

// ── Multi-seller routing ─────────────────────────────────────────────────
// Active SUPPLIER companies — the buyer's "route to seller(s)" picker source.
export const useDealSuppliers = () => useQuery({
  queryKey: ['deal-suppliers'],
  queryFn: crmApi.getDealSuppliers,
  staleTime: 5 * 60_000,
});

/** R1 — предложенные продавцы для заявки (только когда пикер открыт). */
export const useSuggestedSellers = (dealId: number, enabled: boolean) => useQuery({
  queryKey: ['suggested-sellers', dealId],
  queryFn: () => crmApi.getSuggestedSellers(dealId),
  enabled,
  staleTime: 60_000,
});

// R3: buyer opts into an AI-enhanced pass (async 202/poll); merged into the picker on the client.
export const useSuggestSellersAi = () => useMutation({
  mutationFn: (dealId: number) => crmApi.suggestSellersAi(dealId),
});

// Buyer routes a DRAFT RFQ to seller companies. Invalidate the deals list and
// the specific deal detail (key ['deals', id]) so target_sellers_data refreshes.
export const useRouteDeal = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ dealId, sellerCompanyIds }: { dealId: number; sellerCompanyIds: number[] }) =>
      crmApi.routeDeal(dealId, sellerCompanyIds),
    onSuccess: (_data, { dealId }) => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
      queryClient.invalidateQueries({ queryKey: ['deals', dealId] });
    },
  });
};

// ─── Deal ownership / work-queue (ADR-0006 Move 2) ──────────────────────────
export const useClaimDeal = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dealId: number) => crmApi.claimDeal(dealId),
    onSuccess: (_data, dealId) => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
      queryClient.invalidateQueries({ queryKey: ['deals', dealId] });
    },
  });
};

/** W2 «одна кнопка»: claim + стадия + предзаполненный КП (AI для entitled — поллинг внутри api). */
export const useTakeAndPrepareQuote = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dealId: number) => crmApi.takeAndPrepareQuote(dealId),
    onSuccess: (_data, dealId) => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
      queryClient.invalidateQueries({ queryKey: ['deals', dealId] });
      queryClient.invalidateQueries({ queryKey: ['quotes'] });
    },
  });
};

export const useReleaseDeal = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dealId: number) => crmApi.releaseDeal(dealId),
    onSuccess: (_data, dealId) => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
      queryClient.invalidateQueries({ queryKey: ['deals', dealId] });
    },
  });
};

export const useDealStages = () => useQuery({
  queryKey: ['deal-stages'],
  queryFn: crmApi.getDealStages,
  staleTime: 30 * 60_000,
});

// Wedge metric — time-to-first-КП (ADR-0006 Move 4).
export const useTimeToFirstQuote = (sinceDays = 30) => useQuery({
  queryKey: ['time-to-first-quote', sinceDays],
  queryFn: () => crmApi.getTimeToFirstQuote(sinceDays),
  staleTime: 60_000,
});

export const useQuoteStatuses = () => useQuery({
  queryKey: ['quote-statuses'],
  queryFn: crmApi.getQuoteStatuses,
  staleTime: 30 * 60_000,
});

export const useChangeDealStage = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, stage }: { id: number; stage: string }) => crmApi.changeDealStage(id, stage),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['deals'] }),
  });
};

export const useForceChangeDealStage = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, stage, reason }: { id: number; stage: string; reason?: string }) =>
      crmApi.forceChangeDealStage(id, stage, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['deals'] }),
  });
};

export const useDeleteDeal = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => crmApi.deleteDeal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['deals'] }),
  });
};

export const useUpdateDeal = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<import('../../api/crmApi').Deal> }) => crmApi.updateDeal(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

