/**
 * Лиды и ИИ-хуки CRM: подбор по каталогу, пере-привязка товара, предполётная проверка,
 * сверка документа, подсказка ответа в чате, дифф КП.
 *
 * Вынесено из useCRM.ts при распиле (727 строк, 39 правок). Домены зеркалят пакет
 * `@/api/crm`. Путь `@/hooks/useCRM` сохранён барьером — его импортируют 41 файл.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi, MatchCatalogPayload, PreflightPayload, DocCheckPayload } from '../../api/crmApi';
import { aiApi, type ComposeRequestPayload } from '../../api/aiApi';

export const useLeads = () => useQuery({
  queryKey: ["leads"],
  queryFn: crmApi.listLeads,
});

// Оператор НАЗНАЧАЕТ лид компании, компания БЕРЁТ его в работу — два разных действия двух
// разных сторон (Salesforce Lead Queue + Take Ownership). Прежний `useConvertLead` совмещал
// их в одном вызове, который у штатного оператора отказывал всегда.
export const useRouteLead = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, companyId, reason }: { leadId: number; companyId: number; reason: string }) =>
      crmApi.routeLead(leadId, companyId, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });
};

export const useRejectLead = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, reason }: { leadId: number; reason: string }) => crmApi.rejectLead(leadId, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });
};

export const useClaimLead = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (leadId: number) => crmApi.claimLead(leadId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["deals"] });
    },
  });
};

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

// AI #8 conversational заявка builder: POST free-text need → proposed structured
// request lines + catalog candidates. Pure advisory op (no cache to invalidate);
// the buyer reviews/edits/confirms before anything is added. May 503 when AI off.
export const useComposeRequest = () => useMutation({
  mutationFn: (payload: ComposeRequestPayload) => aiApi.composeRequest(payload),
});

// AI #7 pre-flight quality check: POST draft заявка lines → advisory findings.
// Pure advisory op (no cache to invalidate); never blocks the buyer submit.
export const usePreflightCheck = () => useMutation({
  mutationFn: (payload: PreflightPayload) => crmApi.preflightCheck(payload),
});

// AI #6 contract/invoice extraction: POST a signed PDF + quote/contract id → extracted
// fields and a code-computed reconciliation. Pure advisory op (no cache to invalidate);
// the money verdict is recomputed on the backend in Decimal. May 503 when AI disabled.
export const useCheckDocument = () => useMutation({
  mutationFn: (payload: DocCheckPayload) => crmApi.checkDocument(payload),
});

// AI #4 deal-chat reply assist: POST a deal id → a reply DRAFT from recent chat.
// Pure op (no cache to invalidate); the draft fills the input for review/edit,
// never auto-sent. May 503 when AI is disabled — the UI degrades gracefully.
export const useSuggestChatReply = () => useMutation({
  mutationFn: (dealId: number) => crmApi.suggestChatReply(dealId),
});

// AI #3 «КП vs заявка» coverage/diff: GET a received КП id → deterministic coverage
// facts + (when AI on) semantic discrepancies. On-demand paid call → mutation so the
// buyer triggers it explicitly. Read-only & assistive; never blocks. May 503 when off.
export const useQuoteRequestDiff = () => useMutation({
  mutationFn: (quoteId: number) => crmApi.quoteRequestDiff(quoteId),
});
