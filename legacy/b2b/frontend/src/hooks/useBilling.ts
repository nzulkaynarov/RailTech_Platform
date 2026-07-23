import {
  QueryClient, useMutation, useQuery, useQueryClient,
} from '@tanstack/react-query';
import { contractsApi, ContractFilterParams } from '@/api/contractsApi';
import {
  actsApi, invoicesApi, paymentsApi,
  InvoiceFilterParams,
} from '@/api/billingApi';
import { fulfillmentApi, FulfillmentUpdatePayload } from '@/api/fulfillmentApi';

// Wave I-3 — document/billing mutations must refresh the dashboard surfaces (stat counters
// + the «Недавние документы» widget) or they drift stale. Prefix-matches so `['dashboard-stats',
// period]` / `['recent-documents', limit]` variants are all invalidated.
const invalidateDashboardSurfaces = (qc: QueryClient) => {
  qc.invalidateQueries({ queryKey: ['dashboard-stats'] });
  qc.invalidateQueries({ queryKey: ['page-stats'] });
  qc.invalidateQueries({ queryKey: ['recent-documents'] });
};

// ─── Contracts ────────────────────────────────────────────────

export const useContracts = (params?: ContractFilterParams) => useQuery({
  queryKey: ['contracts', params],
  queryFn: () => contractsApi.list(params),
});

export const useContract = (id: number | null) => useQuery({
  queryKey: ['contract', id],
  queryFn: () => contractsApi.get(id as number),
  enabled: !!id,
});

export const useGenerateContract = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ quoteId, notes }: { quoteId: number; notes?: string }) =>
      contractsApi.generateFromQuote(quoteId, notes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['contracts'] });
      qc.invalidateQueries({ queryKey: ['deals'] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

export const useSignContractClient = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => contractsApi.signClient(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ['contracts'] });
      qc.invalidateQueries({ queryKey: ['contract', id] });
    },
  });
};

export const useSignContractManager = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => contractsApi.signManager(id),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ['contracts'] });
      qc.invalidateQueries({ queryKey: ['contract', id] });
    },
  });
};

export const useUploadSignedContract = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) =>
      contractsApi.uploadSigned(id, file),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['contracts'] });
      qc.invalidateQueries({ queryKey: ['contract', id] });
    },
  });
};

export const useCancelContract = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      contractsApi.cancel(id, reason),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['contracts'] });
      qc.invalidateQueries({ queryKey: ['contract', id] });
    },
  });
};

export const useForceCancelContract = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      contractsApi.forceCancel(id, reason),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['contracts'] });
      qc.invalidateQueries({ queryKey: ['contract', id] });
    },
  });
};

// ─── Invoices ─────────────────────────────────────────────────

export const useInvoices = (params?: InvoiceFilterParams) => useQuery({
  queryKey: ['invoices', params],
  queryFn: () => invoicesApi.list(params),
});

export const useInvoice = (id: number | null) => useQuery({
  queryKey: ['invoice', id],
  queryFn: () => invoicesApi.get(id as number),
  enabled: !!id,
});

// WP-G2 — «Создать инвойс с нуля» (DRAFT invoice, contract=null; optional source КП to import
// lines). Refresh the invoices list so the new DRAFT is present when the editor Sheet opens.
export const useCreateInvoiceDraft = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { deal: number; source_quote?: number }) =>
      invoicesApi.createDraft(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['deals'] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

export const useGenerateInvoice = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ contractId, dueDays }: { contractId: number; dueDays?: number }) =>
      invoicesApi.generateFromContract(contractId, dueDays),
    onSuccess: (_data, { contractId }) => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      // Refresh contracts so invoice_id populates and the source contract's
      // "Create invoice" button flips to "Open invoice".
      qc.invalidateQueries({ queryKey: ['contracts'] });
      qc.invalidateQueries({ queryKey: ['contract', contractId] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

export const useRecordPayment = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      invoiceId, amount, paidAt, method, reference, proofFile,
    }: {
      invoiceId: number;
      amount: string;
      paidAt: string;
      method?: string;
      reference?: string;
      proofFile?: File;
    }) =>
      invoicesApi.recordPayment(invoiceId, {
        amount, paid_at: paidAt, method, reference, proof_file: proofFile,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['payments'] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

export const useGenerateAct = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (invoiceId: number) => invoicesApi.generateAct(invoiceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['acts'] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

export const useIssueInvoice = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => invoicesApi.issue(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['invoice', id] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

export const useCancelInvoice = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => invoicesApi.cancel(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['invoice', id] });
      // Cancelling clears the contract's non-cancelled invoice → its `invoice_id` goes null, so the
      // contract Sheet must flip «Открыть инвойс» back to «Создать инвойс» (re-issue after cancel).
      qc.invalidateQueries({ queryKey: ['contracts'] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

export const useUpdateInvoiceDraft = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, dueDate, notes }: { id: number; dueDate?: string; notes?: string }) =>
      invoicesApi.updateDraft(id, { due_date: dueDate, notes }),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['invoice', id] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

// ─── Payments ─────────────────────────────────────────────────

export const usePayments = (params?: { invoice?: number; page?: number }) => useQuery({
  queryKey: ['payments', params],
  queryFn: () => paymentsApi.list(params),
});

// ─── Acts ─────────────────────────────────────────────────────

export const useActs = (params?: { status?: string; deal?: number; page?: number }) => useQuery({
  queryKey: ['acts', params],
  queryFn: () => actsApi.list(params),
});

export const useAct = (id: number | null) => useQuery({
  queryKey: ['act', id],
  queryFn: () => actsApi.get(id as number),
  enabled: !!id,
});

export const useSignAct = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, signedFile }: { id: number; signedFile?: File }) =>
      actsApi.sign(id, signedFile),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['acts'] });
      invalidateDashboardSurfaces(qc);
    },
  });
};

// ─── Fulfillment ──────────────────────────────────────────────

export const useFulfillments = (params?: { status?: string; deal?: number; page?: number }) =>
  useQuery({
    queryKey: ['fulfillments', params],
    queryFn: () => fulfillmentApi.list(params),
  });

export const useUpdateFulfillmentStatus = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: FulfillmentUpdatePayload) => fulfillmentApi.updateStatus(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fulfillments'] });
      qc.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};
