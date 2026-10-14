/**
 * Позиции КП и заявки: точечные и пакетные правки, добавление строк заявки, отправка заявки.
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi, QuoteItemDisplayType } from '../../api/crmApi';

export const useCreateQuoteItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { quote: number; imported_raw_name: string; quantity?: number; frozen_base_price?: string; frozen_currency?: string; display_type?: QuoteItemDisplayType; is_optional?: boolean }) => crmApi.createQuoteItem(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quote-items'] });
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

export const useDeleteQuoteItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => crmApi.deleteQuoteItem(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quote-items'] });
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

// Массовое удаление строк КП (WP-J) — ОДИН транзакционный запрос. Раньше здесь уходили N
// параллельных DELETE (bulk-эндпоинта не было): они брали блокировки строк вразнобой, ловили
// `deadlock detected` в Postgres, и удаление оставалось ЧАСТИЧНЫМ — пользователь видел только
// «Operation failed» и не знал, что именно удалилось. Одиночное удаление (useDeleteQuoteItem)
// не тронуто.
export const useBulkDeleteQuoteItems = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ quoteId, ids }: { quoteId: number; ids: number[] }) =>
      crmApi.bulkDeleteQuoteItems(quoteId, ids),
    // onSettled, NOT onSuccess: a partial failure (3 of 5 deleted, 2 rejected) still
    // changed server state — without invalidation the deleted rows stay visible as
    // phantoms and the next Save sends their ids (adversarial-review MAJOR).
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['quote-items'] });
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

// Bulk create of new КП lines (WP-J duplicate). ONE transactional request, ONE recalc; same
// invalidations as the single-item create so the grid + economics refresh once.
export const useBulkCreateQuoteItems = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ quoteId, items }: { quoteId: number; items: Array<Record<string, unknown>> }) =>
      crmApi.bulkCreateQuoteItems(quoteId, items),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quote-items'] });
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};
