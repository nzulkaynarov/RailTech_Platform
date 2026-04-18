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
