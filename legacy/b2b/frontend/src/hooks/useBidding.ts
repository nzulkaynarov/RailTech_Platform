import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { biddingApi, rfqApi, SubmitBidPayload } from '@/api/biddingApi';

export const useSupplierBids = (params?: { status?: string; deal?: number; supplier?: number }) =>
  useQuery({
    queryKey: ['supplier-bids', params],
    queryFn: () => biddingApi.list(params),
  });

export const useSupplierBid = (id: number | null) => useQuery({
  queryKey: ['supplier-bid', id],
  queryFn: () => biddingApi.get(id as number),
  enabled: !!id,
});

export const useSubmitBid = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SubmitBidPayload) => biddingApi.submit(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['supplier-bids'] }),
  });
};

export const useAcceptBid = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => biddingApi.accept(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['supplier-bids'] });
      qc.invalidateQueries({ queryKey: ['deals'] });
    },
  });
};

export const useRejectBid = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) => biddingApi.reject(id, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['supplier-bids'] }),
  });
};

export const useOpenRfq = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ dealId, supplierIds }: { dealId: number; supplierIds?: number[] }) =>
      rfqApi.openRfq(dealId, supplierIds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['deals'] });
      qc.invalidateQueries({ queryKey: ['supplier-bids'] });
    },
  });
};
