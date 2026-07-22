import { useQuery } from '@tanstack/react-query';
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
