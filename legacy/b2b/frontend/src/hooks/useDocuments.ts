import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  documentTemplatesApi, generatedDocumentsApi,
  CreateTemplatePayload, UpdateTemplatePayload, GenerateDocumentPayload,
} from '@/api/documentsApi';

// ─── Templates ────────────────────────────────────────────────────

export const useDocumentTemplates = () => useQuery({
  queryKey: ['document-templates'],
  queryFn: () => documentTemplatesApi.list(),
});

export const useDocumentTemplate = (id: number | null) => useQuery({
  queryKey: ['document-template', id],
  queryFn: () => documentTemplatesApi.get(id as number),
  enabled: !!id,
});

export const useCreateTemplate = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateTemplatePayload) => documentTemplatesApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['document-templates'] }),
  });
};

export const useUpdateTemplate = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: UpdateTemplatePayload }) =>
      documentTemplatesApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['document-templates'] }),
  });
};

export const useDeleteTemplate = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => documentTemplatesApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['document-templates'] }),
  });
};

export const useCopyTemplate = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => documentTemplatesApi.copy(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['document-templates'] }),
  });
};

// Live-preview mutation — the editor debounces the body before calling.
export const usePreviewTemplate = () => useMutation({
  mutationFn: (bodyHtml: string) => documentTemplatesApi.preview(bodyHtml),
});

// Static placeholder catalog — long staleTime, it is reference data.
export const usePlaceholderCatalog = () => useQuery({
  queryKey: ['document-template-placeholders'],
  queryFn: () => documentTemplatesApi.placeholders(),
  staleTime: 1000 * 60 * 60, // 1h — server-side whitelist rarely changes
});

// ─── Generated documents ──────────────────────────────────────────

export const useGeneratedDocuments = (params?: { status?: string; deal?: number; page?: number }) =>
  useQuery({
    queryKey: ['generated-documents', params],
    queryFn: () => generatedDocumentsApi.list(params),
  });

export const useGeneratedDocument = (id: number | null) => useQuery({
  queryKey: ['generated-document', id],
  queryFn: () => generatedDocumentsApi.get(id as number),
  enabled: !!id,
});

export const useGenerateDocument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: GenerateDocumentPayload) => generatedDocumentsApi.generate(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['generated-documents'] }),
  });
};

export const useUpdateDocumentValues = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, values }: { id: number; values: Record<string, string> }) =>
      generatedDocumentsApi.updateValues(id, values),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['generated-documents'] });
      qc.invalidateQueries({ queryKey: ['generated-document', id] });
    },
  });
};

export const useIssueDocument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => generatedDocumentsApi.issue(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['generated-documents'] });
      qc.invalidateQueries({ queryKey: ['generated-document', id] });
    },
  });
};

export const useCancelDocument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => generatedDocumentsApi.cancel(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['generated-documents'] });
      qc.invalidateQueries({ queryKey: ['generated-document', id] });
    },
  });
};

// F2 II-1: email an ISSUED document. `to` optional (backend falls back to the deal contact).
export const useSendDocument = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, to }: { id: number; to?: string }) => generatedDocumentsApi.sendEmail(id, to),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['generated-documents'] });
      qc.invalidateQueries({ queryKey: ['generated-document', id] });
    },
  });
};
