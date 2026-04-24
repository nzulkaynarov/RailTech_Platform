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

export interface Attachment {
  id: number;
  file: string | null;
  original_filename: string;
  uploaded_by: number | null;
  uploaded_by_email: string | null;
  uploaded_at: string;
  deal?: number | null;
  message?: number | null;
  quote?: number | null;
  company?: number | null;
  product?: number | null;
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
  listAttachments: async (params: {
    deal?: number; message?: number; quote?: number; company?: number; product?: number;
  }): Promise<Attachment[]> => {
    const response = await apiClient.get<PaginatedResponse<Attachment>>('sourcing/attachments/', { params });
    return response.data.results;
  },
  uploadAttachment: async (
    parent: { deal?: number; message?: number; quote?: number; company?: number; product?: number },
    file: File,
  ): Promise<Attachment> => {
    const formData = new FormData();
    formData.append('file', file);
    Object.entries(parent).forEach(([k, v]) => {
      if (v != null) formData.append(k, String(v));
    });
    const response = await apiClient.post<Attachment>('sourcing/attachments/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },
  deleteAttachment: async (id: number): Promise<void> => {
    await apiClient.delete(`sourcing/attachments/${id}/`);
  },
  importCatalog: async (file: File): Promise<{ task_id: string; status: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiClient.post<{ task_id: string; status: string }>(
      'sourcing/import-catalog/',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },
  getImportStatus: async (taskId: string) => {
    const response = await apiClient.get<{
      task_id: string;
      status: string;
      result?: unknown;
      meta?: { current?: number; total?: number };
    }>(`sourcing/import-status/${taskId}/`);
    return response.data;
  },
};
