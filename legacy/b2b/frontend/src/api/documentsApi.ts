import { apiClient } from './client';

// ─── Document templates («Прочие документы» — library) ────────────
//
// Backend contract (crm/serializers/documents.py DocumentTemplateSerializer). The
// generated schema types these loosely (`placeholders_used: unknown`); we narrow
// them locally so the page + hooks (reused by wave-A3) stay strongly typed.

export interface DocumentTemplate {
  id: number;
  name: string;
  kind: string;
  kind_code: string;
  kind_name: string;
  body_html: string;
  placeholders_used: string[];
  is_sample: boolean;
  is_active: boolean;
  is_owned: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateTemplatePayload {
  name: string;
  kind: string;
  body_html: string;
}

export interface UpdateTemplatePayload {
  name?: string;
  kind?: string;
  body_html?: string;
  is_active?: boolean;
}

// ─── Generated documents (rendered instances) ─────────────────────

export type GeneratedDocumentStatus = 'DRAFT' | 'ISSUED' | 'CANCELLED';

export interface GeneratedDocument {
  id: number;
  number: string;
  title: string;
  status: number;
  status_code: GeneratedDocumentStatus;
  status_name: string;
  template: number;
  template_name: string;
  deal: number | null;
  deal_title: string | null;
  contact: number | null;
  contact_name: string | null;
  values: Record<string, string>;
  rendered_html: string;
  pdf_available: boolean;
  issued_at: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface GenerateDocumentPayload {
  template_id: number;
  deal_id?: number;
  contact_id?: number;
  title?: string;
}

// ─── Templates API ────────────────────────────────────────────────
// The template list endpoint sets `pagination_class = None` → a plain array
// (own templates + global platform samples, samples first).

export const documentTemplatesApi = {
  list: async () => {
    const response = await apiClient.get<DocumentTemplate[]>('crm/document-templates/');
    return response.data;
  },
  get: async (id: number) => {
    const response = await apiClient.get<DocumentTemplate>(`crm/document-templates/${id}/`);
    return response.data;
  },
  create: async (payload: CreateTemplatePayload) => {
    const response = await apiClient.post<DocumentTemplate>('crm/document-templates/', payload);
    return response.data;
  },
  update: async (id: number, payload: UpdateTemplatePayload) => {
    const response = await apiClient.patch<DocumentTemplate>(`crm/document-templates/${id}/`, payload);
    return response.data;
  },
  remove: async (id: number) => {
    await apiClient.delete(`crm/document-templates/${id}/`);
  },
  copy: async (id: number) => {
    const response = await apiClient.post<DocumentTemplate>(`crm/document-templates/${id}/copy/`);
    return response.data;
  },
};

// ─── Generated documents API ──────────────────────────────────────
// The generated-documents list is UNPAGINATED (pagination_class = None) → plain array. The registry
// does client-side filter/sort/paging + stat tiles over the full set, so it must receive every row.

export const generatedDocumentsApi = {
  list: async (params?: { status?: string; deal?: number }) => {
    const response = await apiClient.get<GeneratedDocument[]>('crm/generated-documents/', { params });
    return response.data;
  },
  get: async (id: number) => {
    const response = await apiClient.get<GeneratedDocument>(`crm/generated-documents/${id}/`);
    return response.data;
  },
  generate: async (payload: GenerateDocumentPayload) => {
    const response = await apiClient.post<GeneratedDocument>('crm/generated-documents/generate/', payload);
    return response.data;
  },
  updateValues: async (id: number, values: Record<string, string>) => {
    const response = await apiClient.patch<GeneratedDocument>(`crm/generated-documents/${id}/`, { values });
    return response.data;
  },
  issue: async (id: number) => {
    const response = await apiClient.post<GeneratedDocument>(`crm/generated-documents/${id}/issue/`);
    return response.data;
  },
  cancel: async (id: number) => {
    const response = await apiClient.post<GeneratedDocument>(`crm/generated-documents/${id}/cancel/`);
    return response.data;
  },
};
