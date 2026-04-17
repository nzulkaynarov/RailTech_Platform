import { apiClient } from './client';
import { PaginatedResponse } from './types';
import type { Quote } from './crmApi';

export interface SourcingRequest {
  id: number;
  title?: string;
  company?: number | null;
  company_name?: string;
  stage?: number | null;
  stage_code?: string;
  stage_name?: string;
  total_value?: string;
  manager?: number | null;
  active_quote?: Quote | null;
  created_at: string;
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
