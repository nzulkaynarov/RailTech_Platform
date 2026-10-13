/** Запросы мастера первого запуска, чек-листа настройки и резервных копий. */
import { useQueryClient } from "@tanstack/react-query";

import {
  getGetSetupStateQueryKey,
  getListBackupsQueryKey,
  useGetSetupChecklist,
  useGetSetupState,
  useListBackups,
  useRequestBackup as useRequestBackupMutation,
} from "./generated/crm";

/** Ключи, которые страницы кладут в кэш сами (мастер первого запуска). */
export const systemKeys = {
  setupState: getGetSetupStateQueryKey(),
};

export const useSetupState = () => useGetSetupState({ query: { staleTime: 60_000, retry: false } });

export const useSetupChecklist = (enabled: boolean) =>
  useGetSetupChecklist({ query: { enabled, staleTime: 60_000 } });

export const useBackups = () =>
  useListBackups({
    // Пока запрос «сделать сейчас» ждёт сервис бэкапа — обновляем раз в 15 с.
    query: { refetchInterval: (query) => (query.state.data?.requested_at ? 15_000 : false) },
  });

export function useRequestBackup(onError: (error: unknown) => void, onSuccess: () => void) {
  const client = useQueryClient();
  return useRequestBackupMutation({
    mutation: {
      onSuccess: (data) => {
        client.setQueryData(getListBackupsQueryKey(), data);
        onSuccess();
      },
      onError,
    },
  });
}
