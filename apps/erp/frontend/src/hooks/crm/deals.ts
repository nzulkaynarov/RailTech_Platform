/**
 * Сделки и заявки: список/карточка, создание, взятие в работу и освобождение, этапы воронки и
 * статусы КП. Маршрутизация заявки продавцам (R1/R3) удалена в M1-ERP-02 волна 3: продавец один.
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi, QuoteItem } from '../../api/crmApi';

export const useDeals = (opts?: { fetchAll?: boolean }) => useQuery({
  // `fetchAll` — часть ключа: полный список и первая страница это РАЗНЫЕ данные, и без
  // этого виджет дашборда и реестр делили бы один кэш, отдавая друг другу свои двадцать строк.
  queryKey: ['deals', { fetchAll: opts?.fetchAll ?? false }],
  queryFn: () => crmApi.getDeals(opts),
});

export const useDeal = (id: number) => useQuery({
  queryKey: ['deals', id],
  queryFn: () => crmApi.getDeal(id),
  enabled: !!id,
});

/**
 * Цепочка документов сделки для хаба на карточке (F1). Отдельный ключ, а не поле сделки:
 * подпись договора / выставление счёта / оплата обновляют ТОЛЬКО его, не перегружая
 * карточку с её вложенными КП.
 */
export const useDealDocuments = (dealId: number) => useQuery({
  queryKey: ['deal-documents', dealId],
  queryFn: () => crmApi.getDealDocuments(dealId),
  enabled: !!dealId,
});

export interface QuoteItemsFilterParams {
  /** Позиции ОДНОГО КП. Билдер обязан спрашивать именно так: у сделки бывает несколько
   *  документов (контейнер строк заявки клиента и КП), и фильтр по сделке
   *  смешивает их в одну таблицу. */
  quote?: number;
  deal_id?: number;
  product_is_null?: boolean;
}

export const useQuoteItems = (params?: QuoteItemsFilterParams) => useQuery({
  queryKey: ['quote-items', params],
  queryFn: () => crmApi.getQuoteItems(params),
  // Запрос БЕЗ единого фильтра вернул бы все позиции компании — чужие строки
  // в чужой таблице. Пока вызывающий не знает, ЧТО именно грузит (активный КП ещё не
  // приехал), запроса нет: пустой результат честнее случайного.
  enabled: Boolean(params && (params.quote || params.deal_id)),
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
    mutationFn: ({ id, stage, reason }: { id: number; stage: string; reason: string }) =>
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
