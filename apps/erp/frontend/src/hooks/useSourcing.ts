import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { sourcingApi } from '@/api/sourcingApi';

/**
 * Company-wide attachment registry (wave D «Файлы», DMS-lite v1). Returns every
 * attachment the current company can reach (all accessible deals + company/product
 * files; a platform admin sees everything) by walking every paginated page — so the
 * registry is complete, not a silent 20-row slice.
 */
export const useCompanyAttachments = () => useQuery({
  queryKey: ['company-attachments'],
  queryFn: () => sourcingApi.listAllAttachments(),
});

/**
 * Wave I-1 — upload a company-scoped file into the «Файлы» registry (no deal). The
 * backend requires exactly ONE parent; a company file passes `company=<id>` and is
 * magic-byte validated server-side (`validate_document_upload`). Invalidates the
 * registry so the new row appears immediately.
 */
export const useUploadCompanyFile = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ companyId, file }: { companyId: number; file: File }) =>
      sourcingApi.uploadAttachment({ company: companyId }, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['company-attachments'] });
    },
  });
};
