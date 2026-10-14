/**
 * КП: чтение, настройки, применение дефолтов компании, базис поставки, создание,
 * дублирование, отклонение и генерация PDF.
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi } from '../../api/crmApi';

export const useQuotes = () => useQuery({
    queryKey: ['quotes'],
    queryFn: crmApi.getQuotes,
});

export const useQuote = (id: number) => useQuery({
    queryKey: ['quotes', id],
    queryFn: () => crmApi.getQuote(id),
    enabled: !!id,
});

// КП-level: seller sets currency / notes / validity.
export const useUpdateQuote = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, data }: { id: number; data: Parameters<typeof crmApi.updateQuote>[1] }) =>
            crmApi.updateQuote(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['quotes'] });
            queryClient.invalidateQueries({ queryKey: ['deals'] });
        },
    });
};

// КП-level settings (gear panel): seller sets VAT rate / tax country / validity / currency.
// vat_rate feeds VAT, so the backend re-aggregates totals — refresh quotes + deals (active_quote).
export const useUpdateQuoteSettings = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, data }: { id: number; data: Parameters<typeof crmApi.updateQuoteSettings>[1] }) =>
            crmApi.updateQuoteSettings(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['quotes'] });
            queryClient.invalidateQueries({ queryKey: ['deals'] });
            // F5: a quote-level margin/VAT change recomputes EVERY line's final price on the
            // server. Without this the КП builder's line grid kept showing 0% margin + cost-only
            // sums until an unrelated action forced a refetch — a confusing stale view while pricing.
            queryClient.invalidateQueries({ queryKey: ['quote-items'] });
        },
    });
};

// «Применить настройки компании» (Odoo Update Prices): re-pull current company defaults
// into the DRAFT КП. vat/margin move the totals server-side, so refresh the same surfaces
// as a settings save (quotes + deals + line grid).
export const useApplyQuoteDefaults = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.applyQuoteDefaults(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['quotes'] });
            queryClient.invalidateQueries({ queryKey: ['deals'] });
            queryClient.invalidateQueries({ queryKey: ['quote-items'] });
        },
    });
};

// Seller picks Incoterm → basis set + charge template auto-applied. Refresh quotes,
// deals (active_quote), the charges list (template rows appear), and the line grid
// (F5: freight/basis recomputes each line's landed cost → final price).
export const useSetQuoteDeliveryBasis = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, deliveryBasis }: { id: number; deliveryBasis: number }) =>
            crmApi.setQuoteDeliveryBasis(id, deliveryBasis),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['quotes'] });
            queryClient.invalidateQueries({ queryKey: ['deals'] });
            queryClient.invalidateQueries({ queryKey: ['quote-charges'] });
            queryClient.invalidateQueries({ queryKey: ['quote-items'] });
        },
    });
};

export const useCreateQuote = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { deal: number; notes?: string; valid_until?: string }) =>
      crmApi.createQuote(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quotes'] });
      qc.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

// WP-G1 — «Дублировать КП». Deep-copies a quote into a new DRAFT on the same deal and returns
// it. Invalidate quotes + deals (the deal's active_quote flips to the new version) + quote-items
// so the redirected builder shows the filled copy.
export const useDuplicateQuote = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => crmApi.duplicateQuote(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quotes'] });
      qc.invalidateQueries({ queryKey: ['deals'] });
      qc.invalidateQueries({ queryKey: ['quote-items'] });
    },
  });
};
