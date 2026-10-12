/** Запросы мастера первого запуска, чек-листа настройки и резервных копий. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getSetupChecklist, getSetupState, listBackups, requestBackup } from "./generated/crm";
import { unwrap } from "./http";

export const systemKeys = {
  setupState: ["setup", "state"] as const,
  checklist: ["setup", "checklist"] as const,
  backups: ["system", "backups"] as const,
};

export const useSetupState = () =>
  useQuery({
    queryKey: systemKeys.setupState,
    queryFn: async () => unwrap(await getSetupState()),
    staleTime: 60_000,
    retry: false,
  });

export const useSetupChecklist = (enabled: boolean) =>
  useQuery({
    queryKey: systemKeys.checklist,
    queryFn: async () => unwrap(await getSetupChecklist()),
    enabled,
    staleTime: 60_000,
  });

export const useBackups = () =>
  useQuery({
    queryKey: systemKeys.backups,
    queryFn: async () => unwrap(await listBackups()),
    // Пока запрос «сделать сейчас» ждёт сервис бэкапа — обновляем раз в 15 с.
    refetchInterval: (query) => (query.state.data?.requested_at ? 15_000 : false),
  });

export function useRequestBackup(onError: (error: unknown) => void, onSuccess: () => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await requestBackup()),
    onSuccess: (data) => {
      client.setQueryData(systemKeys.backups, data);
      onSuccess();
    },
    onError,
  });
}
