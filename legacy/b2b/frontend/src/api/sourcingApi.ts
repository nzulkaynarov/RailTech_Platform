import { apiClient } from './client';
import { PaginatedResponse } from './types';

export interface Attachment {
  id: number;
  file: string | null;
  original_filename: string;
  kind?: 'SOURCE' | 'SUPPORTING';
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
  listAttachments: async (params: {
    deal?: number; message?: number; quote?: number; company?: number; product?: number;
  }): Promise<Attachment[]> => {
    const response = await apiClient.get<PaginatedResponse<Attachment>>('sourcing/attachments/', { params });
    return response.data.results;
  },
  // Company-wide file registry (wave D «Файлы»). The endpoint is paginated
  // (PageNumberPagination, PAGE_SIZE=20) and does NOT expose a `page_size` query
  // param, so a single request would silently truncate the registry to 20 rows.
  // We walk every page via the paginator's `next` link to build the COMPLETE list
  // (a bounded loop guards against a misbehaving API), so the UI can be honest
  // about totals instead of showing a partial slice.
  listAllAttachments: async (): Promise<Attachment[]> => {
    const MAX_PAGES = 50; // 50 × 20 = 1000 files ceiling for v1 — plenty, and never unbounded
    const all: Attachment[] = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const response = await apiClient.get<PaginatedResponse<Attachment>>(
        'sourcing/attachments/',
        { params: { page } },
      );
      all.push(...response.data.results);
      if (!response.data.next) break;
    }
    return all;
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
  importCatalog: async (file: File, dryRun = false): Promise<{ task_id: string; status: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('dry_run', dryRun ? 'true' : 'false');
    const response = await apiClient.post<{ task_id: string; status: string }>(
      'sourcing/import-catalog/',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },
  downloadCatalogTemplate: async (): Promise<Blob> => {
    const response = await apiClient.get('sourcing/catalog-template/', { responseType: 'blob' });
    return response.data as Blob;
  },
  getImportStatus: async (taskId: string) => {
    const response = await apiClient.get<{
      task_id: string;
      status: string;
      result?: CatalogImportResult | null;
      meta?: { current?: number; total?: number };
    }>(`sourcing/import-status/${taskId}/`);
    return response.data;
  },
};

export interface CatalogImportResult {
  status?: string;
  message?: string | null;
  dry_run?: boolean | null;
  created?: number | null;
  updated?: number | null;
  offers_upserted?: number | null;
  skipped?: number | null;
  error_count?: number | null;
  errors?: { row: number; message: string }[] | null;
  items_processed?: number | null;
}
