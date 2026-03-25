import { apiClient } from './client';
import { PaginatedResponse } from './types';

export interface SourcingRequest {
  id: number;
  number: string;
  client_name: string;
  items_count: number;
  matched_count: number;
  status: string;
  created_at: string;
}

export interface SourcingItem {
  id: number;
  name: string;
  article: string;
  gost: string;
  uom: string;
  quantity: number;
  match_status: 'matched' | 'partial' | 'not_found';
  matched_product_id?: number;
  manufacturer_name?: string;
  base_price?: number;
  rfq_status?: string;
}

export const sourcingApi = {
  getRequests: async (): Promise<SourcingRequest[]> => {
    const response = await apiClient.get<PaginatedResponse<SourcingRequest>>('sourcing/requests/');
    return response.data.results;
  },
  getRequestDetail: async (id: number) => {
    const response = await apiClient.get(`sourcing/requests/${id}/`);
    return response.data;
  },
};
