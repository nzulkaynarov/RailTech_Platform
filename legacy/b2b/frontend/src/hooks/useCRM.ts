import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { crmApi, QuoteItem } from '../api/crmApi';

export const useDeals = () => useQuery({
  queryKey: ['deals'],
  queryFn: crmApi.getDeals,
});

export const useDeal = (id: number) => useQuery({
  queryKey: ['deals', id],
  queryFn: () => crmApi.getDeal(id),
  enabled: !!id,
});

export const useAnalytics = () => useQuery({
  queryKey: ['crm-analytics'],
  queryFn: crmApi.getAnalytics,
  refetchInterval: 60_000,
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

export const useDealStages = () => useQuery({
  queryKey: ['deal-stages'],
  queryFn: crmApi.getDealStages,
  staleTime: 30 * 60_000,
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
    mutationFn: ({ dealId, ...data }: { dealId: number; name: string; quantity: number; unit?: string; unit_code?: string; note?: string }) =>
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

export const useQuotes = () => useQuery({
    queryKey: ['quotes'],
    queryFn: crmApi.getQuotes,
});

export const useQuote = (id: number) => useQuery({
    queryKey: ['quotes', id],
    queryFn: () => crmApi.getQuote(id),
    enabled: !!id,
});

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

export const useConfirmQuoteTradeReview = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.confirmQuoteTradeReview(id),
        onSuccess: () => invalidateQuoteChain(queryClient),
    });
};

export const useDirectorApproveQuote = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: number) => crmApi.directorApproveQuote(id),
        onSuccess: () => invalidateQuoteChain(queryClient),
    });
};

export const useSendQuoteBack = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, reason }: { id: number; reason: string }) =>
            crmApi.sendQuoteBack(id, reason),
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
