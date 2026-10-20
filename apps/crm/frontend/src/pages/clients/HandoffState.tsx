import { Alert, Button } from "antd";

import type { ClientDetail } from "../../api/generated/model";
import { useHandoffRetry } from "../../hooks/useHandoffRetry";
import { t } from "../../i18n/ru";
import { handoffErrorText, retryLeadId } from "./handoffText";

type AlertProps = {
  status: "pending" | "done" | "failed" | null | undefined;
  error: string | null | undefined;
  /** Куда повторять передачу: клиент и лид, из которого её запускали. */
  clientId: number;
  leadId: number | null;
  canWrite: boolean;
};

/**
 * Состояние передачи клиента в бэк-офис (FIX-31): «передаётся» / ошибка с причиной и кнопкой
 * «Повторить передачу». Передан — отдельной строки не нужно: в реквизитах уже есть компания ERP.
 * Общий для карточки клиента и карточки лида (FIX-34b).
 */
export function HandoffAlert({ status, error, clientId, leadId, canWrite }: AlertProps) {
  const retry = useHandoffRetry(clientId, leadId);
  if (status === "pending") {
    return (
      <Alert
        type="info"
        showIcon
        message={t.clients.handoffPending}
        description={
          error
            ? `${t.clients.handoffPendingHint} ${t.clients.handoffPendingError.replace("{error}", handoffErrorText(error))}`
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
      description={handoffErrorText(error)}
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

/** Состояние передачи в карточке клиента: повтор идёт из его последнего лида в стадии «клиент». */
export function HandoffState({ client, canWrite }: { client: ClientDetail; canWrite: boolean }) {
  return (
    <HandoffAlert
      status={client.erp_handoff_status}
      error={client.erp_handoff_error}
      clientId={client.id}
      leadId={retryLeadId(client)}
      canWrite={canWrite}
    />
  );
}
