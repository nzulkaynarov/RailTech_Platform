import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Button } from "antd";

import { adminKeys } from "../../api/adminQueries";
import { getListClientsQueryKey, makeCustomer } from "../../api/generated/crm";
import type { ClientDetail } from "../../api/generated/model";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { handoffErrorText } from "./handoffText";

/** Последний лид клиента — из него идёт повторная передача (тот же вызов, что «Передать в бэк-офис»). */
function retryLeadId(client: ClientDetail): number | null {
  return client.leads.reduce<number | null>(
    (max, lead) => (max === null || lead.id > max ? lead.id : max),
    null,
  );
}

function useRetry(client: ClientDetail) {
  const query = useQueryClient();
  const { message } = AntApp.useApp();
  return useMutation({
    mutationFn: async () => {
      const leadId = retryLeadId(client);
      if (leadId === null) throw new Error(t.clients.handoffNoLead);
      return await makeCustomer(leadId, { client_id: client.id, new_client_name: null });
    },
    onSuccess: () => {
      void message.success(t.clients.handoffRetryQueued);
      void query.invalidateQueries({ queryKey: adminKeys.client(client.id) });
      void query.invalidateQueries({ queryKey: getListClientsQueryKey() });
    },
    onError: useApiErrorToast(),
  });
}

/**
 * Состояние передачи клиента в бэк-офис (FIX-31): «передаётся» / ошибка с причиной и кнопкой
 * «Повторить передачу». Передан — отдельной строки не нужно: в реквизитах уже есть компания ERP.
 */
export function HandoffState({ client, canWrite }: { client: ClientDetail; canWrite: boolean }) {
  const retry = useRetry(client);
  const status = client.erp_handoff_status;
  if (status === "pending") {
    return (
      <Alert
        type="info"
        showIcon
        message={t.clients.handoffPending}
        description={
          client.erp_handoff_error
            ? `${t.clients.handoffPendingHint} ${t.clients.handoffPendingError.replace("{error}", handoffErrorText(client.erp_handoff_error))}`
            : t.clients.handoffPendingHint
        }
      />
    );
  }
  if (status !== "failed") return null;
  return (
    <Alert
      type="error"
      showIcon
      message={t.clients.handoffFailed}
      description={handoffErrorText(client.erp_handoff_error)}
      action={
        canWrite ? (
          <Button
            size="small"
            loading={retry.isPending}
            onClick={() => {
              retry.mutate();
            }}
          >
            {t.clients.handoffRetry}
          </Button>
        ) : null
      }
    />
  );
}
