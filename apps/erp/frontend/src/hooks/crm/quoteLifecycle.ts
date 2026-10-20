/**
 * Жизненный цикл КП: отправка клиенту, публичная ссылка, согласование и цепочка
 * внутреннего ревью, очередь согласований.
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi } from '../../api/crmApi';

export const useSendQuoteToClient = () => {
    const queryClient = useQueryClient();
    return useMutation({
        // S7a: pass an optional justification (required by the backend when below the margin floor).
        mutationFn: ({ id, justification }: { id: number; justification?: string }) =>
            crmApi.sendQuoteToClient(id, justification),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['quotes'] });
            queryClient.invalidateQueries({ queryKey: ['deals'] });
        },
    });
};

// Wave B2 — revoke the КП public share link from the post-send panel. Refresh quotes + deals
// so the panel reflects the new public_token_revoked state (copy/revoke controls update).
export const useRevokePublicLink = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.revokePublicLink(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['quotes'] });
            queryClient.invalidateQueries({ queryKey: ['deals'] });
        },
    });
};

/* ── КП internal approval chain (документооборот) ────────────────────────
 * Each step invalidates quotes + deals + quote-items so the КП status badge,
 * the deal card, and the builder grid all refresh after the transition. */
const invalidateQuoteChain = (queryClient: ReturnType<typeof useQueryClient>) => {
    queryClient.invalidateQueries({ queryKey: ['quotes'] });
    queryClient.invalidateQueries({ queryKey: ['deals'] });
    queryClient.invalidateQueries({ queryKey: ['quote-items'] });
    queryClient.invalidateQueries({ queryKey: ['my-approval-queue'] });
};

// DRAFT-stage approval preview (Salesforce pattern): read-only, fetched only while a draft's
// chain popover can show it — tells the seller up-front who will have to approve, or that the
// chain will auto-approve (solo).
export const useQuoteApprovalPreview = (id: number, enabled: boolean) => useQuery({
    queryKey: ['quotes', id, 'approval-preview'],
    queryFn: () => crmApi.getQuoteApprovalPreview(id),
    enabled: enabled && !!id,
});

export const useSubmitQuoteForReview = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.submitQuoteForReview(id),
        onSuccess: () => invalidateQuoteChain(queryClient),
    });
};

export const useActOnApprovalStep = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, stepId, decision, comment }: { id: number; stepId: number; decision: 'APPROVE' | 'REJECT'; comment?: string }) =>
            crmApi.approvalAct(id, stepId, decision, comment || ''),
        onSuccess: () => invalidateQuoteChain(queryClient),
    });
};

export const useRecallQuote = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.recallQuote(id),
        onSuccess: () => invalidateQuoteChain(queryClient),
    });
};

export const useMyApprovalQueue = () => useQuery({
    queryKey: ['my-approval-queue'],
    queryFn: crmApi.getMyApprovalQueue,
});
