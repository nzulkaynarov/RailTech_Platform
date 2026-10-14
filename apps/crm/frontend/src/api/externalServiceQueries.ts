/** Запросы «Внешних сервисов» (M3-CRM-12): список, деталка, «Проверить сейчас», выключатели. */
import { useQueryClient } from "@tanstack/react-query";

import {
  getGetExternalServiceQueryKey,
  getListExternalServicesQueryKey,
  getSystemStatusQueryKey,
  useCheckExternalService,
  useDisableExternalService,
  useEnableExternalService,
  useGetExternalService,
  useListExternalServices,
} from "./generated/crm";

/** Фоновые проверки — раз в минуту; страница обновляется с той же частотой. */
const REFRESH_MS = 60_000;

export const useExternalServices = () =>
  useListExternalServices({ query: { refetchInterval: REFRESH_MS } });

export const useExternalService = (key: string) =>
  useGetExternalService(key, { query: { refetchInterval: REFRESH_MS, retry: false } });

/** После проверки или выключателя — список, деталка и «Состояние системы» сразу актуальны. */
function useInvalidate() {
  const client = useQueryClient();
  return (key: string) => {
    void client.invalidateQueries({ queryKey: getListExternalServicesQueryKey() });
    void client.invalidateQueries({ queryKey: getGetExternalServiceQueryKey(key) });
    void client.invalidateQueries({ queryKey: getSystemStatusQueryKey() });
  };
}

export function useCheckService(onError: (error: unknown) => void, onDone?: () => void) {
  const invalidate = useInvalidate();
  const client = useQueryClient();
  return useCheckExternalService({
    mutation: {
      onSuccess: (data, { key }) => {
        client.setQueryData(getGetExternalServiceQueryKey(key), data);
        invalidate(key);
        onDone?.();
      },
      onError,
    },
  });
}

export function useServiceSwitch(onError: (error: unknown) => void, onDone: () => void) {
  const invalidate = useInvalidate();
  const options = {
    mutation: {
      onSuccess: (_: unknown, { key }: { key: string }) => {
        invalidate(key);
        onDone();
      },
      onError,
    },
  };
  return { disable: useDisableExternalService(options), enable: useEnableExternalService(options) };
}
