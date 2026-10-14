/**
 * Совместная работа: лента активности, таймлайн сделки и компании,
 * контакты и офлайн-клиенты.
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi, OfflineClientPayload } from '../../api/crmApi';

// CRM Phase A — deal-scoped activity timeline (read-only history feed).
export const useDealTimeline = (dealId: number) => useQuery({
    queryKey: ['timeline', 'deal', dealId],
    queryFn: () => crmApi.getTimeline({ deal_id: dealId }),
    enabled: !!dealId,
});

// CRM Phase B — company-scoped timeline (the counterparty card's history feed).
export const useCompanyTimeline = (companyId: number) => useQuery({
    queryKey: ['timeline', 'company', companyId],
    queryFn: () => crmApi.getTimeline({ company_id: companyId }),
    enabled: !!companyId,
});

// Contacts of the team's OWN client book — the «Новый КП» recipient picker (Wave E F2).
export const useContacts = () => useQuery({
    queryKey: ['contacts'],
    queryFn: crmApi.getContacts,
    staleTime: 60_000,
});

// «Завести оффлайн-клиента» — creates a client company edge + primary contact,
// so both the book and the contacts list refresh.
export const useCreateOfflineClient = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: OfflineClientPayload) => crmApi.createOfflineClient(payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['relationships'] });
            queryClient.invalidateQueries({ queryKey: ['contacts'] });
        },
    });
};
