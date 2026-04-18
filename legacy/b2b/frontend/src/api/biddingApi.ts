import { apiClient } from './client';
import { PaginatedResponse } from './types';

export type SupplierBidStatus =
  | 'DRAFT'
  | 'SUBMITTED'
  | 'ACCEPTED'
  | 'REJECTED'
  | 'WITHDRAWN';

export interface SupplierBidItem {
  id: number;
  quote_item: number | null;
  product: number | null;
  description: string;
  quantity: number;
  unit_price: string;
  lead_time_days: number | null;
}

export interface SupplierBid {
  id: number;
  deal: number;
  supplier: number;
  supplier_name: string;
  submitted_by: number | null;
  status: SupplierBidStatus;
  total_amount: string;
  currency: number | null;
  lead_time_days: number | null;
  notes: string;
  submitted_at: string | null;
  accepted_at: string | null;
  items: SupplierBidItem[];
  created_at: string;
  updated_at: string;
}

export interface SubmitBidPayload {
  deal_id: number;
  supplier_id: number;
  items: Array<{
    quote_item_id?: number | null;
    product_id?: number | null;
    description: string;
    quantity: number;
    unit_price: string;
    lead_time_days?: number | null;
  }>;
  notes?: string;
  lead_time_days?: number;
  currency_id?: number;
}

export const biddingApi = {
  list: async (params?: { status?: string; deal?: number; supplier?: number; page?: number }) => {
    const response = await apiClient.get<PaginatedResponse<SupplierBid>>('crm/supplier-bids/', {
      params,
    });
    return response.data.results;
  },
  get: async (id: number) => {
    const response = await apiClient.get<SupplierBid>(`crm/supplier-bids/${id}/`);
    return response.data;
  },
  submit: async (payload: SubmitBidPayload) => {
    const response = await apiClient.post<SupplierBid>('crm/supplier-bids/submit/', payload);
    return response.data;
  },
  accept: async (id: number) => {
    const response = await apiClient.post<SupplierBid>(`crm/supplier-bids/${id}/accept/`);
    return response.data;
  },
  reject: async (id: number, reason?: string) => {
    const response = await apiClient.post<SupplierBid>(`crm/supplier-bids/${id}/reject/`, {
      reason: reason ?? '',
    });
    return response.data;
  },
};

// ─── RFQ operations on Deal ───────────────────────────────────

export const rfqApi = {
  openRfq: async (dealId: number, supplierIds?: number[]) => {
    const response = await apiClient.post(`crm/deals/${dealId}/open-rfq/`, {
      supplier_ids: supplierIds ?? [],
    });
    return response.data;
  },
};
