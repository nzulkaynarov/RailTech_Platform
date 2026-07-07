import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  crmApi, QuoteItem, QuoteCharge, MatchCatalogPayload, PreflightPayload, DocCheckPayload,
  RelationshipDirection, RelationshipStage, OfflineClientPayload,
} from '../api/crmApi';
import { aiApi, type ComposeRequestPayload } from '../api/aiApi';
import { accountsApi } from '../api/accountsApi';

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

export const useCreateDeal = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { title?: string; notes?: string }) => crmApi.createDeal(data),
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
    mutationFn: ({ id, data }: { id: number; data: Partial<import('../api/crmApi').Deal> }) => crmApi.updateDeal(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

export const useCreateQuoteItem = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { quote: number; imported_raw_name: string; quantity: number; frozen_base_price?: string; frozen_currency?: string }) => crmApi.createQuoteItem(data),
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

export const useActivityLogs = () => useQuery({
    queryKey: ['activity-logs'],
    queryFn: () => crmApi.getActivityLogs(),
});

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

// ─── CRM Phase B — counterparty relationship book («Книга контрагентов») ────
export const useRelationships = (direction?: RelationshipDirection) => useQuery({
    queryKey: ['relationships', direction ?? 'all'],
    queryFn: () => crmApi.getRelationships(direction),
});

// PATCH is limited to the two human-managed fields: stage verdict + account owner.
export const useUpdateRelationship = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, data }: { id: number; data: { stage?: RelationshipStage; owner_member?: number | null } }) =>
            crmApi.updateRelationship(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['relationships'] });
        },
    });
};

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

// CRM Phase D — invite an offline client's contact to register and claim its company.
export const useInviteContact = () => useMutation({
    mutationFn: (contactId: number) => accountsApi.inviteContact(contactId),
});

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

export const useSendQuoteToClient = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.sendQuoteToClient(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['quotes'] });
            queryClient.invalidateQueries({ queryKey: ['deals'] });
        },
    });
};

export const useApproveQuote = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.approveQuote(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['quotes'] });
            queryClient.invalidateQueries({ queryKey: ['deals'] });
        },
    });
};

export const useForceApproveQuote = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, reason }: { id: number; reason: string }) =>
            crmApi.forceApproveQuote(id, reason),
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


export const useLeads = () => useQuery({
  queryKey: ["leads"],
  queryFn: crmApi.listLeads,
});

export const useConvertLead = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, companyId }: { leadId: number; companyId?: number }) =>
      crmApi.convertLead(leadId, companyId),
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

export const useRejectQuote = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) => crmApi.rejectQuote(id, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quotes'] });
      qc.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

export const useGenerateQuotePDF = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (quoteId: number) => crmApi.generateQuotePDF(quoteId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['quotes'] });
      qc.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};
