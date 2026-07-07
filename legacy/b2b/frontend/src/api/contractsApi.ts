import { apiClient } from './client';
import { PaginatedResponse } from './types';

export type ContractStatus =
  | 'DRAFT'
  | 'PENDING_CLIENT'
  | 'PENDING_MANAGER'
  | 'SIGNED'
  | 'CANCELLED';

export interface Contract {
  id: number;
  deal: number;
  quote: number;
  number: string;
  status: ContractStatus;
  total_amount: string;
  currency: number | null;
  pdf_file: string | null;
  pdf_url: string | null;
  signed_file: string | null;
  signed_file_url: string | null;
  client_signer: number | null;
  client_signer_name: string | null;
  client_signed_at: string | null;
  manager_signer: number | null;
  manager_signer_name: string | null;
  manager_signed_at: string | null;
  valid_from: string | null;
  valid_until: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface ContractFilterParams {
  status?: string;
  deal?: number;
  ordering?: string;
  page?: number;
  search?: string;
  [key: string]: string | number | boolean | undefined;
}

export const contractsApi = {
  list: async (params?: ContractFilterParams) => {
    const response = await apiClient.get<PaginatedResponse<Contract>>('crm/contracts/', { params });
    return response.data.results;
  },
  get: async (id: number) => {
    const response = await apiClient.get<Contract>(`crm/contracts/${id}/`);
    return response.data;
  },
  // Stream the PDF through the authenticated endpoint — the raw pdf_url (/media/…)
  // 404s on prod (local storage, no MinIO). Polls through 202 GENERATING (ARCH-03).
  downloadPdf: async (id: number) => {
    const { downloadFile } = await import('@/lib/download');
    await downloadFile(`crm/contracts/${id}/download-pdf/`, `RailTech_Contract_${id}.pdf`);
  },
  generateFromQuote: async (quoteId: number, notes?: string) => {
    const response = await apiClient.post<Contract>('crm/contracts/generate-from-quote/', {
      quote_id: quoteId,
      notes: notes ?? '',
    });
    return response.data;
  },
  signClient: async (id: number) => {
    const response = await apiClient.post<Contract>(`crm/contracts/${id}/sign-client/`);
    return response.data;
  },
  signManager: async (id: number) => {
    const response = await apiClient.post<Contract>(`crm/contracts/${id}/sign-manager/`);
    return response.data;
  },
  uploadSigned: async (id: number, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await apiClient.post<Contract>(`crm/contracts/${id}/upload-signed/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },
  cancel: async (id: number, reason?: string) => {
    const response = await apiClient.post<Contract>(`crm/contracts/${id}/cancel/`, {
      reason: reason ?? '',
    });
    return response.data;
  },
  forceCancel: async (id: number, reason: string) => {
    const response = await apiClient.post<Contract>(`crm/contracts/${id}/force-cancel/`, { reason });
    return response.data;
  },
  remove: async (id: number) => {
    await apiClient.delete(`crm/contracts/${id}/`);
  },
};
