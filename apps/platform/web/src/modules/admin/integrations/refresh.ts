import { useQueryClient } from "@tanstack/react-query";

/** Сброс кэша всех запросов экрана после действия: обзор и открытые панели перечитываются. */
export function useRefreshIntegrations(): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/admin/integrations"),
    });
  };
}
