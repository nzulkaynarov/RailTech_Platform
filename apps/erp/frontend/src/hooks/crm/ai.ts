/**
 * ИИ-хуки CRM: подбор по каталогу, пере-привязка товара, сверка документа. (Лиды и подсказка
 * ответа в чате удалены в M1-ERP-02 1b; покупательские ИИ-помощники заявки — составление из
 * текста, предполётная проверка, «КП vs заявка» — в волне 3.)
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi, MatchCatalogPayload, DocCheckPayload } from '../../api/crmApi';

export const useMatchCandidates = (quoteItemId: number | null) => useQuery({
  queryKey: ["match-candidates", quoteItemId],
  queryFn: () => crmApi.matchCandidates(quoteItemId as number),
  enabled: !!quoteItemId,
  staleTime: 0,
});

export const useReassignProduct = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ quoteItemId, productId }: { quoteItemId: number; productId: number | null }) =>
      crmApi.reassignProduct(quoteItemId, productId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quote-items"] });
      qc.invalidateQueries({ queryKey: ["quotes"] });
      qc.invalidateQueries({ queryKey: ["deals"] });
    },
  });
};


// AI catalog match: POST unmatched lines → candidate products. Pure query op
// (no cache to invalidate); binding happens via useUpdateQuoteItem afterwards.
export const useMatchCatalog = () => useMutation({
  mutationFn: (payload: MatchCatalogPayload) => crmApi.matchCatalog(payload),
});

// AI #6 contract/invoice extraction: POST a signed PDF + quote/contract id → extracted
// fields and a code-computed reconciliation. Pure advisory op (no cache to invalidate);
// the money verdict is recomputed on the backend in Decimal. May 503 when AI disabled.
export const useCheckDocument = () => useMutation({
  mutationFn: (payload: DocCheckPayload) => crmApi.checkDocument(payload),
});
