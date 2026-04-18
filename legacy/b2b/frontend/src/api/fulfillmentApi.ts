import { apiClient } from './client';
import { PaginatedResponse } from './types';

export type FulfillmentStatus =
  | 'PENDING'
  | 'SHIPPED'
  | 'IN_TRANSIT'
  | 'DELIVERED'
  | 'ACCEPTED'
  | 'DISPUTED';

export interface Fulfillment {
  id: number;
  deal: number;
  contract: number | null;
  status: FulfillmentStatus;
  shipped_at: string | null;
  delivered_at: string | null;
  accepted_at: string | null;
  expected_delivery_date: string | null;
  tracking_number: string;
  carrier: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface FulfillmentUpdatePayload {
  deal_id: number;
  status: FulfillmentStatus;
  tracking_number?: string;
  carrier?: string;
  expected_delivery_date?: string;
  notes?: string;
}

export const fulfillmentApi = {
  list: async (params?: { status?: string; deal?: number; page?: number }) => {
    const response = await apiClient.get<PaginatedResponse<Fulfillment>>('crm/fulfillments/', {
      params,
    });
    return response.data.results;
  },
  get: async (id: number) => {
    const response = await apiClient.get<Fulfillment>(`crm/fulfillments/${id}/`);
    return response.data;
  },
  updateStatus: async (payload: FulfillmentUpdatePayload) => {
    const response = await apiClient.post<Fulfillment>('crm/fulfillments/update-status/', payload);
    return response.data;
  },
};
