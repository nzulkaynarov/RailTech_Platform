import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp } from "antd";

import { adminKeys } from "../api/adminQueries";
import { getGetLeadQueryKey, getListClientsQueryKey, makeCustomer } from "../api/generated/crm";
import { t } from "../i18n/ru";
import { useApiErrorToast } from "./useApiErrorToast";

/**
 * Передача клиента в бэк-офис ещё раз (FIX-31, FIX-34b): тот же вызов `make_customer`, что и
 * «Передать в бэк-офис»; бэкенд сам отличает повтор от первой передачи. Из карточки клиента и
 * из карточки лида — одна и та же логика.
 */
export function useHandoffRetry(clientId: number | null, leadId: number | null) {
  const query = useQueryClient();
  const { message } = AntApp.useApp();
  return useMutation({
    mutationFn: async () => {
      if (clientId === null || leadId === null) throw new Error(t.clients.handoffNoLead);
      return await makeCustomer(leadId, { client_id: clientId, new_client_name: null });
    },
    onSuccess: () => {
      void message.success(t.clients.handoffRetryQueued);
      if (clientId !== null) void query.invalidateQueries({ queryKey: adminKeys.client(clientId) });
      if (leadId !== null) void query.invalidateQueries({ queryKey: getGetLeadQueryKey(leadId) });
      void query.invalidateQueries({ queryKey: getListClientsQueryKey() });
    },
    onError: useApiErrorToast(),
  });
}
