/**
 * Статьи расхода и скидки уровня КП: типы, шаблоны, CRUD и переупорядочивание.
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi, QuoteCharge } from '../../api/crmApi';

// ── КП-level expense items / discounts (charges) ─────────────────────────
export const useChargeTypes = () => useQuery({
    queryKey: ['charge-types'],
    queryFn: crmApi.getChargeTypes,
    staleTime: 5 * 60_000,
});

// Org-admin: the company's per-Incoterm charge templates.
export const useChargeTemplates = () => useQuery({
    queryKey: ['charge-templates'],
    queryFn: crmApi.getChargeTemplates,
});

export const useCreateChargeTemplate = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data: Parameters<typeof crmApi.createChargeTemplate>[0]) => crmApi.createChargeTemplate(data),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['charge-templates'] }),
    });
};

export const useDeleteChargeTemplate = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.deleteChargeTemplate(id),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['charge-templates'] }),
    });
};

export const useQuoteCharges = (quoteId?: number) => useQuery({
    queryKey: ['quote-charges', quoteId],
    queryFn: () => crmApi.getQuoteCharges(quoteId as number),
    enabled: !!quoteId,
});

// Charges change the КП total (charges_total → vat → total), so refresh quotes,
// deals (active_quote totals), and the charges list.
const invalidateCharges = (queryClient: ReturnType<typeof useQueryClient>) => {
    queryClient.invalidateQueries({ queryKey: ['quote-charges'] });
    queryClient.invalidateQueries({ queryKey: ['quotes'] });
    queryClient.invalidateQueries({ queryKey: ['deals'] });
};

export const useCreateQuoteCharge = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data: Parameters<typeof crmApi.createQuoteCharge>[0]) => crmApi.createQuoteCharge(data),
        onSuccess: () => invalidateCharges(queryClient),
    });
};

export const useUpdateQuoteCharge = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, data }: { id: number; data: Partial<QuoteCharge> }) =>
            crmApi.updateQuoteCharge(id, data),
        onSuccess: () => invalidateCharges(queryClient),
    });
};

export const useDeleteQuoteCharge = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.deleteQuoteCharge(id),
        onSuccess: () => invalidateCharges(queryClient),
    });
};

export const useReorderQuoteCharges = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ quoteId, order }: { quoteId: number; order: number[] }) =>
            crmApi.reorderQuoteCharges(quoteId, order),
        onSuccess: () => invalidateCharges(queryClient),
    });
};

