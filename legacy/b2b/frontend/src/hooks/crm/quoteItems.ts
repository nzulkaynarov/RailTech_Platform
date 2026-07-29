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

// Bulk delete of КП lines (WP-J). Fires the per-row deletes in parallel (there is no
// bulk-delete endpoint) but invalidates the caches ONCE at the end — N per-call invalidations
// would thrash the grid. Single-line delete (useDeleteQuoteItem) is left untouched.
export const useBulkDeleteQuoteItems = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) => Promise.all(ids.map((id) => crmApi.deleteQuoteItem(id))),
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

// Buyer-only: append a row to their own request. Backend creates the DRAFT
// quote on first add and rejects once the seller has engaged (can_edit_request).
export const useAddRequestItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ dealId, ...data }: { dealId: number; name: string; quantity: number; unit?: string; unit_code?: string; note?: string; mpn?: string }) =>
      crmApi.addRequestItem(dealId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quote-items'] });
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

// Buyer-only: edit the request header (title + note to seller) while DRAFT.
export const useUpdateRequestMeta = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ dealId, ...data }: { dealId: number; title?: string; notes?: string }) =>
      crmApi.updateRequestMeta(dealId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

// Buyer-only: submit the request (RFQ) to the seller — Draft → RFQ_OPEN.
export const useSubmitRequest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dealId: number) => crmApi.submitRequest(dealId),
    onSuccess: (_data, dealId) => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
      // P2-8: the submit-RFQ ActivityLog is written server-side, but the deal
      // history feed served a stale ['timeline','deal',id] cache until reload —
      // refresh it so «Заявка отправлена поставщику (RFQ)» appears immediately.
      queryClient.invalidateQueries({ queryKey: ['timeline', 'deal', dealId] });
    },
  });
};

